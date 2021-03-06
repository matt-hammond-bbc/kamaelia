#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# Copyright 2010 British Broadcasting Corporation and Kamaelia Contributors(1)
#
# (1) Kamaelia Contributors are listed in the AUTHORS file and at
#     http://www.kamaelia.org/AUTHORS - please extend this file,
#     not this notice.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# -------------------------------------------------------------------------
"""
First pass of a "Log file" generator.

Generates logfiles with the following characteristics:
   * You can define a mean number of concurrent users for the majority
     of the logfile
   * You can define the number of sites those concurrent users are
     accessing
   * You define the number of desired requests in the logfile
   * You can define a percentage sampling size, a default sampler of
     100% is provided.
   * You can change the sampling method to a custom one by implementing
     a new method, and any others your sampling requires.
   * You can set and receive cookies from clients.

Things to do:
   * Add setting to clients as to whether they will correctly retain the
     cookie
   * Modify sampling method to handle "zero" memory density biassed sampling.
   * Validate that the accuracy is sufficient.
   * Validate assumption that memory consumption is proportional to the
     granularity of site density, not proportional to the number of users.
     (even density biassed suffers from this at present due to seen/unseen
     filters)
"""
#########################################################################
#
#            Configuration
#
percentageSample = 100
desiredNumberOfRequests = 100000
concurrentUsers=500
numberOfSites = 100

import math
import random
RAND_MAX=2147483647
class zipf:
   """Zipf distribution generator.
   * The algorithm here is directly adapted from:
   * http://www.cs.hut.fi/Opinnot/T-106.290/K2004/Ohjeet/Zipf.html

   N # Value range [1,N]
   a  # Distribution skew. Zero = uniform.
   c1,c2 # Computed once for all random no.s for N and a
   """
   def __init__(self,N=10000,a=1):
      self.N = N
      if a < 0.0001:
         self.a = 0.0
         self.c1 = 0.0
         self.c2 = 0.0
      elif 0.9999 <a < 1.0001:
         self.a = 1.0
         self.c1 = math.log(N+1)
         self.c2 = 0.0
      else:
         self.a = float(a)
         self.c1 = math.exp((1-a) * math.log(N+1)) - 1
         self.c2 = 1.0 / (1-a)

   def __repr__(self):
      return "zipf( " + str(self.N) + ", " + str(self.a) + ") : " + str(self.c1) + ", " + str(self.c2)

   def next(self):
      r = 0
      x = 0.0
      if self.a == 0:
         return random.randint(1,self.N)
      while r <= 1 or r>self.N:
         x = random.random()
         if self.a == 1:
            x = math.exp(x * self.c1);
         else:
            x = math.exp(self.c2 * math.log(x * self.c1 + 1));
         r=int(x)
      return r

class client:
   """
   A client is classified by:
            * The number of requests they will make:
               Heavily tailed (Inverse Gaussian) distribution, typical mean 3, standard deviation 9, mode of 1
            * Whether they can handle cookies correctly (assume 90% even)
            * What their currently set cookie is
            * How many times they come back (-1 is infinitely repeating)
            * How often they come back (This is a request delay)
            * Are allocated a pseudorandom IP number.
               * This is not guaranteed to be unique (simulate effect of proxies)
            * They do not follow any particular request pattern, other than that generated by zipf.
   """
   def __init__(self):
      self._ip = "192.168.0."+str(random.randint(1,128))
      self._cookie = "XXXX"
   def ip(self):
      return self._ip
   def cookie(self):
      return self._cookie
   def set_cookie(self, cookie):
      self._cookie = cookie
   def __repr__(self):
      return str(id(self))

class requestStream:
   """
   A request stream is a sequence of client IP, client cookie, request (zipf number), client
   In order to generate this it tracks:
            * A list of clients
            * Addition of new clients throughout the time period
            * Deletion of expired clients
            * Which clients are making a request
   The user can configure the following attributes:
      * concurrentUsers : This is a rough indication on the number of
        concurrent users for a long running stream
   """
   def __init__(self, concurrentUsers=1000,sites=10000):
      self._users = concurrentUsers*2
      Z=zipf(N=numberOfSites)
      self._nextRequest = Z.next

   def addClient(self):
         C=client()
         self.clients.append(C)

   def removeClient(self):
      c = random.randint(1,len(self.clients))-1
      self.clients[c] = self.clients[len(self.clients)-1]
      del self.clients[len(self.clients)-1]

   def pickClient(self):
      try:
         c = random.randint(1,len(self.clients))-1
         C = self.clients[c]
      except ValueError:
         C=client()
         self.clients.append(C)
      return C

   def handleClientQueue(self):
         if random.randint(1,self._users)>len(self.clients):
            self.addClient()
         else:
            self.removeClient()

   def main(self):
      self.clients = []
      while 1:
         C=self.pickClient()
         self.handleClientQueue()
         yield [C.ip(), C.cookie(), self._nextRequest(), C]

#
# Need to merge the new version
#
def likelihood_old(numSamples, targetSample):
   "NB, this can return > 1.0"
   try:
      return 1/float(numSamples) + targetSample/100.
   except ZeroDivisionError:
       return 1

def likelihood(numSamples, target, numRequests=1): # This can return > 1.0
   """Returns a likelyhood of sampling the next request based on
   """
   try:
      currentRate= numSamples/float(numRequests)
      # The 100 in the next line was found empiricially, and is needed to
      # force the two rates to converge reliably at a reliable rate.
      result = 100*   (1-(currentRate/target))
      return result
   except ZeroDivisionError:
      return 1

class userSampling:
   def __init__(self, percent):
      self._percent=percent
      self._siteTrack = {}
      self._siteSamples = {}

   def dumpSampleDB(self):
      print "SITE, REQ, SAMP, RATE"
      sites = self._siteTrack.keys()
      sites.sort()
      for site in sites:
         print site, ",",
         print self._siteTrack[site], ",",
         print self._siteSamples[site], ",",
         print int((self._siteSamples[site]/float(self._siteTrack[site]))*1000)/10.

   def updateTrackSites(self, request):
      self._siteTrack[request[2]] = self._siteTrack.get(request[2],0)+1

   def updateClient(self, request):
      "Override this method to change realtime sampling method"
      # Unless we match the cookies, we miss the first request
      self.updateTrackSites(request)
      if random.random() < likelihood(self._siteSamples.get(request[2],0), 0.22, self._siteTrack[request[2]]):
         request[3].set_cookie("sample")
         request[1]="sample"

   def sampling(self, request):
      self.updateClient(request)
      if req[1]=="sample":
         self._siteSamples[request[2]] = self._siteSamples.get(request[2],0)+1
         return True
      else:
         return False

sampler = userSampling(percentageSample)
XS=requestStream(concurrentUsers=concurrentUsers,sites=numberOfSites)
X=XS.main()

for i in xrange(desiredNumberOfRequests):
   req = X.next()
   if sampler.sampling(req):
      #print i, req, "sample"
      pass
   else:
      #print i, req, "reject"
      pass

sampler.dumpSampleDB()

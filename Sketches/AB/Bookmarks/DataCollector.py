#! /usr/bin/python

# Saves relevant data fed back from TwitterStream etc next to its PID and timestamp ready for analysis
# Needs to do limited analysis to work out which keywords in the tweet stream correspond to which programme
# Keywords, and possibly PIDs and channels will most likely have to be passed here as well as to the TwitterStream from Requester

import time as time2
import MySQLdb
import cjson
import string
from datetime import datetime
from time import time
from dateutil.parser import parse
import _mysql_exceptions
import os

from Axon.ThreadedComponent import threadedcomponent

class DataCollector(threadedcomponent):
    Inboxes = {
        "inbox" : "Receives data in the format [tweetjson,[pid,pid]]",
        "control" : ""
    }
    Outboxes = {
        "outbox" : "",
        "signal" : ""
    }

    def __init__(self,dbuser,dbpass):
        super(DataCollector, self).__init__()
        self.dbuser = dbuser
        self.dbpass = dbpass

    def finished(self):
        while self.dataReady("control"):
            msg = self.recv("control")
            if isinstance(msg, producerFinished) or isinstance(msg, shutdownMicroprocess):
                self.send(msg, "signal")
                return True
        return False

    def dbConnect(self):
        db = MySQLdb.connect(user=self.dbuser,passwd=self.dbpass,db="twitter_bookmarks",use_unicode=True,charset="utf8")
        cursor = db.cursor()
        return cursor

    def main(self):
        cursor = self.dbConnect()
        while not self.finished():
            twitdata = list()
            while self.dataReady("inbox"):
                pids = list()
                data = self.recv("inbox")
                for pid in data[1]:
                    pids.append(pid)
                twitdata.append([data[0],pids])
            if len(twitdata) > 0:

                for tweet in twitdata:
                    tweet[0] = tweet[0].replace("\\/","/") # This may need moving further down the line - ideally it would be handled by cjson
                    if tweet[0] != "\r\n":
                        # At this point, each 'tweet' contains tweetdata, and a list of possible pids
                        newdata = cjson.decode(tweet[0]) # Won't work - need keywords to be related to their pids - let's requery
                        if newdata.has_key('delete') or newdata.has_key('scrub_geo') or newdata.has_key('limit'):
                            # Trying to work out what content is set to at the point it fails
                            filepath = "contentDebug.txt"
                            if os.path.exists(filepath):
                                file = open(filepath, 'r')
                                filecontents = file.read()
                            else:
                                filecontents = ""
                            file = open(filepath, 'w')
                            file.write(filecontents + "\n" + str(datetime.utcnow()) + " " + cjson.encode(newdata))
                            file.close()
                        else:
                            tweetid = newdata['id']
                            print "New tweet! @" + newdata['user']['screen_name'] + ": " + newdata['text']
                            for pid in tweet[1]:
                                # Cycle through possible pids, grabbing that pid's keywords from the DB
                                # Then, check this tweet against the keywords and save to DB where appropriate (there may be more than one location)
                                cursor.execute("""SELECT keyword,type FROM keywords WHERE pid = %s""",(pid))
                                data = cursor.fetchall()
                                for row in data:
                                    keywords = row[0].split("^")
                                    if len(keywords) == 2:
                                        if string.lower(keywords[0]) in string.lower(newdata['text']) and string.lower(keywords[1]) in string.lower(newdata['text']):
                                            cursor.execute("""SELECT timestamp,timediff FROM programmes WHERE pid = %s""",(pid))
                                            progdata = cursor.fetchone()
                                            if progdata != None:
                                                # Ensure the user hasn't already tweeted for this programme in this minute
                                                # Muppet - this will only check for same second tweets - duh
                                                cursor.execute("""SELECT * FROM rawdata WHERE pid = %s AND text = %s AND user = %s""",(pid,newdata['text'],newdata['user']['screen_name']))
                                                if cursor.fetchone() == None:
                                                    print ("Storing tweet for pid " + pid)
                                                    timestamp = time2.mktime(parse(newdata['created_at']).timetuple())
                                                    progposition = timestamp - progdata[0] + progdata[1]
                                                    cursor.execute("""INSERT INTO rawdata (tweet_id,pid,timestamp,text,user,programme_position) VALUES (%s,%s,%s,%s,%s,%s)""", (tweetid,pid,timestamp,newdata['text'],newdata['user']['screen_name'],progposition))
                                                    break # Break out of this loop and back to check the same tweet against the next programme
                                                else:
                                                    print ("Duplicate user for current minute - ignoring")
                                    if string.lower(row[0]) in string.lower(newdata['text']):
                                        cursor.execute("""SELECT timestamp,timediff FROM programmes WHERE pid = %s""",(pid))
                                        progdata = cursor.fetchone()
                                        if progdata != None:
                                            # Ensure the user hasn't already tweeted for this programme in this minute
                                            # Muppet - this will only check for same second tweets - duh
                                            cursor.execute("""SELECT * FROM rawdata WHERE pid = %s AND text = %s AND user = %s""",(pid,newdata['text'],newdata['user']['screen_name']))
                                            if cursor.fetchone() == None:
                                                print ("Storing tweet for pid " + pid)
                                                timestamp = time2.mktime(parse(newdata['created_at']).timetuple())
                                                progposition = timestamp - progdata[0] + progdata[1]
                                                cursor.execute("""INSERT INTO rawdata (tweet_id,pid,timestamp,text,user,programme_position) VALUES (%s,%s,%s,%s,%s,%s)""", (tweetid,pid,timestamp,newdata['text'],newdata['user']['screen_name'],progposition))
                                                break # Break out of this loop and back to check the same tweet against the next programme
                                            else:
                                                print ("Duplicate user for current minute - ignoring")
                    else:
                        print "Blank line received from Twitter - no new data"
                    
                    print ("Done!") # new line to break up display
            else:
                time2.sleep(0.1)


class RawDataCollector(threadedcomponent):
    Inboxes = {
        "inbox" : "Receives data in the format [tweetjson,[pid,pid]]",
        "control" : ""
    }
    Outboxes = {
        "outbox" : "",
        "signal" : ""
    }

    def __init__(self,dbuser,dbpass):
        super(RawDataCollector, self).__init__()
        self.dbuser = dbuser
        self.dbpass = dbpass

    def finished(self):
        while self.dataReady("control"):
            msg = self.recv("control")
            if isinstance(msg, producerFinished) or isinstance(msg, shutdownMicroprocess):
                self.send(msg, "signal")
                return True
        return False

    def dbConnect(self):
        db = MySQLdb.connect(user=self.dbuser,passwd=self.dbpass,db="twitter_bookmarks",use_unicode=True,charset="utf8")
        cursor = db.cursor()
        return cursor

    def main(self):
        cursor = self.dbConnect()
        while not self.finished():
            twitdata = list()
            while self.dataReady("inbox"):
                data = self.recv("inbox")
                twitdata.append(data[0])
            if len(twitdata) > 0:

                for tweet in twitdata:
                    tweet = tweet.replace("\\/","/") # This may need moving further down the line - ideally it would be handled by cjson
                    if tweet != "\r\n":
                        newdata = cjson.decode(tweet)
                        if newdata.has_key('delete') or newdata.has_key('scrub_geo') or newdata.has_key('limit'):
                            print "Discarding tweet instruction - captured by other component"
                        else:
                            tweetid = newdata['id']
                            tweetstamp = time()
                            tweetsecs = int(tweetstamp)
                            tweetfrac = tweetstamp - tweetsecs
                            if len(tweet) < 16000:
                                try:
                                    cursor.execute("""INSERT INTO rawtweets (tweet_id,tweet_json,tweet_stored_seconds,tweet_stored_fraction) VALUES (%s,%s,%s,%s)""", (tweetid,tweet,tweetsecs,tweetfrac))
                                except _mysql_exceptions.IntegrityError, e:
                                    print "Duplicate tweet ID:", str(e)
                            else:
                                print "Discarding tweet - length limit exceeded"
                                tweetcontents = ""
                                homedir = os.path.expanduser("~")
                                if os.path.exists(homedir + "/oversizedtweets.conf"):
                                    try:
                                        file = open(homedir + "/oversizedtweets.conf",'r')
                                        tweetcontents = file.read()
                                        file.close()
                                    except IOError, e:
                                        print ("Failed to load oversized tweet cache - it will be overwritten")
                                try:
                                    file = open(homedir + "/oversizedtweets.conf",'w')
                                    tweetcontents = tweetcontents + tweet
                                    file.write(tweetcontents)
                                    file.close()
                                except IOError, e:
                                    print ("Failed to save oversized tweet cache")
            else:
                time2.sleep(0.1)
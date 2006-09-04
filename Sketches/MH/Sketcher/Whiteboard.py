#!/usr/bin/env python
#
# (C) 2006 British Broadcasting Corporation and Kamaelia Contributors(1)
#     All Rights Reserved.
#
# You may only modify and redistribute this under the terms of any of the
# following licenses(2): Mozilla Public License, V1.1, GNU General
# Public License, V2.0, GNU Lesser General Public License, V2.1
#
# (1) Kamaelia Contributors are listed in the AUTHORS file and at
#     http://kamaelia.sourceforge.net/AUTHORS - please extend this file,
#     not this notice.
# (2) Reproduced in the COPYING file, and at:
#     http://kamaelia.sourceforge.net/COPYING
# Under section 3.5 of the MPL, we are using this text since we deem the MPL
# notice inappropriate for this file. As per MPL/GPL/LGPL removal of this
# notice is prohibited.
#
# Please contact us via: kamaelia-list-owner@lists.sourceforge.net
# to discuss alternative licensing.
# -------------------------------------------------------------------------
#

import Axon
import pygame

from Axon.Component import component
from Axon.Ipc import WaitComplete, producerFinished, shutdownMicroprocess
from Kamaelia.UI.Pygame.Button import Button
from Kamaelia.Util.Console import ConsoleReader, ConsoleEchoer
from Kamaelia.Util.Graphline import Graphline
from Kamaelia.Util.Backplane import Backplane, publishTo, subscribeTo
from Kamaelia.Util.PipelineComponent import pipeline
from Kamaelia.Visualisation.PhysicsGraph.chunks_to_lines import chunks_to_lines
from Kamaelia.Visualisation.PhysicsGraph.lines_to_tokenlists import lines_to_tokenlists as text_to_tokenlists

#
# The following application specific components will probably be rolled
# back into the repository.
#

from Whiteboard.TagFiltering import TagAndFilterWrapper, FilterAndTagWrapper
from Whiteboard.Tokenisation import tokenlists_to_lines, lines_to_tokenlists

from Whiteboard.Canvas import Canvas
from Whiteboard.Painter import Painter
from Whiteboard.TwoWaySplitter import TwoWaySplitter
from Whiteboard.SingleShot import OneShot
from Whiteboard.CheckpointSequencer import CheckpointSequencer


# stuff for doing audio
import sys
sys.path.append("../pymedia/")
sys.path.append("../")
sys.path.append("../audio")
#from pymedia_test import SoundOutput,SoundInput,ExtractData,PackageData

from Audio.PyMedia.Input  import Input  as _SoundInput
from Audio.PyMedia.Output import Output as _SoundOutput

from Speex import SpeexEncode,SpeexDecode
from RawAudioMixer import RawAudioMixer as _RawAudioMixer
from Whiteboard.TagFiltering import TagAndFilterWrapperKeepingTag, FilterAndTagWrapperKeepingTag

from Kamaelia.Util.Detuple import SimpleDetupler
from Whiteboard.Entuple import Entuple
from Whiteboard.Router import Router


def SoundInput():
    return _SoundInput( channels=1, sample_rate=8000, format="S16_LE" )

def SoundOutput():
    return _SoundOutput( channels=1, sample_rate=8000, format="S16_LE" )

def RawAudioMixer():
    return _RawAudioMixer( sample_rate    = 8000,
                           channels       = 1,
                           format         = "S16_LE",
                           readThreshold  = 0.2,
                           bufferingLimit = 0.4,
                           readInterval   = 0.05,
                         )


colours = { "black" :  (0,0,0), 
            "red" :    (192,0,0),
            "orange" : (192,96,0),
            "yellow" : (160,160,0),
            "green" :  (0,192,0),
            "turquoise" : (0,160,160),
            "blue": (0,0,255),
            "purple" : (192,0,192),
            "darkgrey" : (96,96,96),
            "lightgrey" :(192,192,192),
          }

colours_order = [ "black", "red", "orange", "yellow", "green", "turquoise", "blue", "purple", "darkgrey", "lightgrey" ]

import os
num_pages = len(os.listdir("Scribbles"))


def buildPalette(cols, order, topleft=(0,0), size=32):
    buttons = {}
    links = {}
    pos = topleft
    i=0
    # Interesting/neat trick MPS
    for col in order:
        buttons[col] = Button(caption="", position=pos, size=(size,size), bgcolour=cols[col], msg=cols[col])
        links[ (col,"outbox") ] = ("self","outbox")
        pos = (pos[0] + size, pos[1])
        i=i+1
    return Graphline( linkages = links,  **buttons )

def parseOptions():
    rhost, rport = None, None
    serveport = None

    shortargs = ""
    longargs  = [ "serveport=", "connectto=" ]
    optlist, remargs = getopt.getopt(sys.argv[1:], shortargs, longargs)

    for o,a in optlist:
        if o in ("-s","--serveport"):
            serveport = int(a)

        elif o in ("-c","--connectto"):
            rhost,rport = re.match(r"^([^:]+):([0-9]+)$", a).groups()
            rport = int(rport)

    return rhost, rport, serveport

def LocalEventServer(whiteboardBackplane="WHITEBOARD", audioBackplane="AUDIO", port=1500):
        from Kamaelia.Chassis.ConnectedServer import SimpleServer
        from Kamaelia.Util.Console import ConsoleEchoer

        def clientconnector():
            return pipeline(
                chunks_to_lines(),
                lines_to_tokenlists(),
                Graphline(
                    WHITEBOARD = FilterAndTagWrapper(
                        pipeline( publishTo(whiteboardBackplane),
                                  # well, should be to separate pipelines, this is lazier!
                                  subscribeTo(whiteboardBackplane),
                                )),
                    AUDIO = pipeline(
                        SimpleDetupler(1),     # remove 'SOUND' tag
                        SpeexDecode(3),
                        FilterAndTagWrapperKeepingTag(
                            pipeline( publishTo(audioBackplane),
                                        # well, should be to separate pipelines, this is lazier!
                                    subscribeTo(audioBackplane),
                                    ),
                            ),
                        RawAudioMixer(),
                        SpeexEncode(3),
                        Entuple(prefix=["SOUND"],postfix=[]),
                        ),
                    ROUTER = Router( ((lambda tuple : tuple[0]=="SOUND"), "audio"),
                                     ((lambda tuple : tuple[0]!="SOUND"), "whiteboard"),
                                   ),
                    linkages = {
                        # incoming messages go to a router
                        ("", "inbox") : ("ROUTER", "inbox"),
                        
                        # distribute messages to appropriate destinations
                        ("ROUTER",      "audio") : ("AUDIO",      "inbox"),
                        ("ROUTER", "whiteboard") : ("WHITEBOARD", "inbox"),
                        
                        # aggregate all output
                        ("AUDIO",      "outbox") : ("", "outbox"),
                        ("WHITEBOARD", "outbox") : ("", "outbox"),
                        
                        # shutdown routing, not sure if this will actually work, but hey!
                        ("", "control") : ("ROUTER", "control"),
                        ("ROUTER", "signal") : ("AUDIO", "control"),
                        ("AUDIO", "signal") : ("WHITEBOARD", "control"),
                        ("WHITEBOARD", "signal") : ("", "signal")
                        },
                    ),
                tokenlists_to_lines(),
                )
        

        return SimpleServer(protocol=clientconnector, port=port)

def EventServerClients(rhost, rport, whiteboardBackplane="WHITEBOARD", audioBackplane="AUDIO"):
        # plug a TCPClient into the backplae
        from Kamaelia.Internet.TCPClient import TCPClient

        loadingmsg = "Fetching sketch from server..."

        return Graphline(
                NETWORK = pipeline(
                    tokenlists_to_lines(),
                    TCPClient(host=rhost,port=rport),
                    chunks_to_lines(),
                    lines_to_tokenlists(),
                ),
                ROUTER = Router( ((lambda tuple : tuple[0]=="SOUND"), "audio"),
                                 ((lambda tuple : tuple[0]!="SOUND"), "whiteboard"),
                               ),
                WHITEBOARD = FilterAndTagWrapper(
                    pipeline(
                        publishTo(whiteboardBackplane),
                        #
                        subscribeTo(whiteboardBackplane),
                    )
                ),
                AUDIO = pipeline(
                    SimpleDetupler(1),     # remove 'SOUND' tag
                    SpeexDecode(3),
                    FilterAndTagWrapperKeepingTag(
                        pipeline(
                            publishTo(audioBackplane),
                            #
                            subscribeTo(audioBackplane),
                        ),
                    ),
                    RawAudioMixer(),
                    SpeexEncode(3),
                    Entuple(prefix=["SOUND"],postfix=[]),
                ),
                GETIMG = OneShot(msg=[["GETIMG"]]),
                BLACKOUT = OneShot(msg=[["CLEAR",0,0,0],["WRITE",100,100,24,255,255,255,loadingmsg]]),
                linkages = {
                    # incoming messages from network connection go to a router
                    ("NETWORK", "outbox") : ("ROUTER", "inbox"),
                    
                    # distribute messages to appropriate destinations
                    ("ROUTER", "audio")      : ("AUDIO",      "inbox"),
                    ("ROUTER", "whiteboard") : ("WHITEBOARD", "inbox"),
                    
                    # aggregate all output, and send across the network connection
                    ("AUDIO",      "outbox") : ("NETWORK", "inbox"),
                    ("WHITEBOARD", "outbox") : ("NETWORK", "inbox"),
                    
                    # initial messages sent to the server, and the local whiteboard
                    ("GETIMG",   "outbox") : ("NETWORK",    "inbox"),
                    ("BLACKOUT", "outbox") : ("WHITEBOARD", "inbox"),
                    
                    # shutdown routing, not sure if this will actually work, but hey!
                    ("NETWORK",    "signal") : ("ROUTER",     "control"),
                    ("ROUTER",     "signal") : ("AUDIO",      "control"),
                    ("AUDIO",      "signal") : ("WHITEBOARD", "control"),
                    ("WHITEBOARD", "signal") : ("",           "signal"),
                }
            )

#-----------------------

def parseCommands():
    from Kamaelia.Util.Marshalling import Marshaller

    class CommandParser:
        def marshall(data):
            output = [data]
            if data[0].upper() == "LOAD":
                output.append(["GETIMG"])    # to propogate loaded image to other connected canvases
            return output
        marshall = staticmethod(marshall)

    return Marshaller(CommandParser)

class PreFilter(Axon.Component.component): # This is a data tap/siphon/demuxer
    Outboxes = ["history_event", "outbox"]
    def main(self):
        while 1:
            while self.dataReady("inbox"):
                data = self.recv("inbox")
                print "INCOMING", data
                if (data == [["prev"]]) or (data == [["next"]]):
                    self.send((data[0][0], "local"), "history_event")
                else:
                    self.send(data, "outbox")
            if not self.anyReady():
                self.pause()
            yield 1


def makeBasicSketcher(left=0,top=0,width=1024,height=768):
    return Graphline( CANVAS  = Canvas( position=(left,top+32),size=(width,height-32) ),
                      PAINTER = Painter(),
                      PALETTE = buildPalette( cols=colours, order=colours_order, topleft=(left+64,top), size=32 ),
                      ERASER  = Button(caption="Eraser", size=(64,32), position=(left,top)),

                      PREV  = Button(caption="<<",
                                     size=(63,32), 
                                     position=(left+64+32*len(colours), top),
                                     msg='prev'),
                      NEXT  = Button(caption=">>",
                                     size=(63,32), 
                                     position=(left+(64*2)+32*len(colours), top),
                                     msg='next'),
                      CHECKPOINT  = Button(caption="checkpoint",
                                     size=(63,32),
                                     position=(left+(64*3)+32*len(colours), top),
                                     msg="checkpoint"),
                      CLEAR  = Button(caption="clear",
                                     size=(63,32),
                                     position=(left+(64*4)+32*len(colours), top),
                                     msg=[["clear"]]),
                      NEWPAGE  = Button(caption="new page",
                                     size=(63,32),
                                     position=(left+(64*5)+32*len(colours), top),
                                     msg="new"),

                      REMOTEPREV  = Button(caption="~~<<~~",
                                     size=(63,32), 
                                     position=(left+(64*6)+32*len(colours), top),
                                     msg=[['prev']]),
                      REMOTENEXT  = Button(caption="~~>>~~",
                                     size=(63,32), 
                                     position=(left+(64*7)+32*len(colours), top),
                                     msg=[['next']]),

                      PREFILTER = PreFilter(),

                      HISTORY = CheckpointSequencer(lambda X: [["LOAD", "Scribbles/slide.%d.png" % (X,)]],
                                                    lambda X: [["SAVE", "Scribbles//slide.%d.png" % (X,)]],
                                                    lambda X: [["CLEAR"]],
                                                    initial = 1,
                                                    highest = num_pages,
                                ),

                      SPLIT   = TwoWaySplitter(),
                      SPLIT2  = TwoWaySplitter(),
                      DEBUG   = ConsoleEchoer(),

                      linkages = {
                          ("CANVAS",  "eventsOut") : ("PAINTER", "inbox"),
                          ("PALETTE", "outbox")    : ("PAINTER", "colour"),
                          ("ERASER", "outbox")     : ("PAINTER", "erase"),

                          ("CLEAR","outbox")       : ("CANVAS", "inbox"),
                          ("NEWPAGE","outbox")     : ("HISTORY", "inbox"),

#                          ("REMOTEPREV","outbox")  : ("self", "outbox"),
#                          ("REMOTENEXT","outbox")  : ("self", "outbox"),
                          ("REMOTEPREV","outbox")  : ("SPLIT2", "inbox"),
                          ("REMOTENEXT","outbox")  : ("SPLIT2", "inbox"),

                          ("SPLIT2", "outbox")      : ("PREFILTER", "inbox"),
                          ("SPLIT2", "outbox2")     : ("self", "outbox"), # send to network


                          ("PREV","outbox")        : ("HISTORY", "inbox"),
                          ("NEXT","outbox")        : ("HISTORY", "inbox"),
                          ("CHECKPOINT","outbox")  : ("HISTORY", "inbox"),
                          ("HISTORY","outbox")     : ("CANVAS", "inbox"),

                          ("PAINTER", "outbox")    : ("SPLIT", "inbox"),
                          ("SPLIT", "outbox")      : ("CANVAS", "inbox"),
                          ("SPLIT", "outbox2")     : ("self", "outbox"), # send to network

                          ("self", "inbox")        : ("PREFILTER", "inbox"),
                          ("PREFILTER", "outbox")  : ("CANVAS", "inbox"),
                          ("PREFILTER", "history_event")  : ("HISTORY", "inbox"),
                          ("CANVAS", "outbox")     : ("self", "outbox"),

                          ("CANVAS","surfacechanged") : ("HISTORY", "inbox"),
                          },
                    )

mainsketcher = \
    Graphline( SKETCHER = makeBasicSketcher(width=1024,height=768),
               CONSOLE = pipeline(ConsoleReader(),text_to_tokenlists(),parseCommands()),

               linkages = { ('self','inbox'):('SKETCHER','inbox'),
                            ('SKETCHER','outbox'):('self','outbox'),
                            ('CONSOLE','outbox'):('SKETCHER','inbox'),
                          }
                 )



if __name__=="__main__":
    
    # primary whiteboard
    pipeline( subscribeTo("WHITEBOARD"),
            TagAndFilterWrapper(mainsketcher),
            publishTo("WHITEBOARD")
            ).activate()
            
    # primary sound IO - tagged and filtered, so can't hear self
    pipeline( subscribeTo("AUDIO"),
              TagAndFilterWrapperKeepingTag(
                  pipeline(
                      RawAudioMixer(),
#                      PackageData(channels=1,sample_rate=8000,format="S16_LE"),
                      SoundOutput(),
                      ######
                      SoundInput(),
#                      ExtractData(),
                  ),
              ),
              publishTo("AUDIO"),
            ).activate()
            
    import sys, getopt, re

    rhost, rport, serveport = parseOptions()

    # setup a server, if requested
    if serveport:
        LocalEventServer("WHITEBOARD", "AUDIO", port=serveport).activate()


    # connect to remote host & port, if requested
    if rhost and rport:
        EventServerClients(rhost, rport, "WHITEBOARD", "AUDIO").activate()

#    sys.path.append("../Introspection")
#    from Profiling import FormattedProfiler
#    
#    pipeline(FormattedProfiler( 20.0, 1.0),
#             ConsoleEchoer()
#            ).activate()

    Backplane("WHITEBOARD").activate()
    Backplane("AUDIO").run()
    
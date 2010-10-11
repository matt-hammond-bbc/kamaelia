from piston.handler import BaseHandler
from bookmarks.output.models import programmes, keywords, analyseddata
from datetime import timedelta,datetime
from dateutil.parser import parse

class ProgrammesHandler(BaseHandler):
    allowed_methods = ('GET',)
    # The below could be used if I wasn't adding keywords too - not sure how to imply some sort of JOIN operation
    #fields = ('pid', 'channel', 'title', 'expectedstart', 'timediff', 'duration', 'imported', 'analysed', 'totaltweets', 'meantweets', 'mediantweets', 'modetweets', 'stdevtweets')
    #model = programmes

    def read(self, request, pid):
        retdata = dict()
        data = programmes.objects.filter(pid=pid)
        if len(data) == 1:
            retdata['status'] = "OK"
            retdata['pid'] = data[0].pid
            retdata['title'] = data[0].title
            retdata['expectedstart'] = data[0].expectedstart
            retdata['timediff'] = data[0].timediff
            retdata['duration'] = data[0].duration
            retdata['imported'] = data[0].imported
            retdata['analysed'] = data[0].analysed
            retdata['totaltweets'] = data[0].totaltweets
            retdata['meantweets'] = data[0].meantweets
            retdata['mediantweets'] = data[0].mediantweets
            retdata['modetweets'] = data[0].modetweets
            retdata['stdevtweets'] = data[0].stdevtweets
            kwdata = keywords.objects.filter(pid=pid).all()
            retdata['keywords'] = list()
            for row in kwdata:
                retdata['keywords'].append({'keyword' : row.keyword, 'type' : row.type})
            retdata['bookmarks'] = list()

            progdate = parse(data[0].expectedstart)
            tz = progdate.tzinfo
            progdate = progdate.replace(tzinfo=None)
            actualstart = progdate - timedelta(seconds=data[0].timediff)
            minutedata = analyseddata.objects.filter(pid=pid).order_by('datetime').all()
            tweetmins = dict()
            lastwasbookmark = False
            bookmarks = list()
            bookmarkcont = list()
            for minute in minutedata:
                # This isn't the most elegant BST solution, but it appears to work
                offset = datetime.strptime(str(tz.utcoffset(parse(minute.datetime))),"%H:%M:%S")
                offset = timedelta(hours=offset.hour)
                tweettime = parse(minute.datetime) + offset
                proghour = tweettime.hour - actualstart.hour
                progmin = tweettime.minute - actualstart.minute
                progsec = tweettime.second - actualstart.second
                playertime = (((proghour * 60) + progmin) * 60) + progsec - 90 # needs between 60 and 120 secs removing to allow for tweeting time - using 90 for now
                if playertime > (data[0].duration - 60):
                    playertimemin = (data[0].duration/60) - 1
                    playertimesec = playertime%60
                elif playertime > 0:
                    playertimemin = playertime/60
                    playertimesec = playertime%60
                else:
                    playertimemin = 0
                    playertimesec = 0
                if minute.totaltweets > (1.5*data[0].stdevtweets+data[0].meantweets):
                    if lastwasbookmark == True:
                        bookmarkcont.append(playertimemin)
                    else:
                        if minute.totaltweets > (2.2*data[0].stdevtweets+data[0].meantweets):
                            lastwasbookmark = True
                            bookmarks.append(playertimemin)
                        else:
                            lastwasbookmark = False
                else:
                    lastwasbookmark = False
                if not tweetmins.has_key(str(playertimemin)):
                    tweetmins[str(playertimemin)] = int(minute.totaltweets)
            if len(tweetmins) > 0:
                xlist = range(0,data[0].duration/60)
                for min in xlist:
                    if min in bookmarks and max(tweetmins.values()) > 9: # Arbitrary value chosen for now - needs experimentation - was 9
                        retdata['bookmarks'].append({'iplayer' : "http://bbc.co.uk/i/" + pid + "/?t=" + str(min) + "m" + str(playertimesec) + "s", 'startseconds' : min*60+playertimesec, 'endseconds' : min*60+playertimesec+60})
                        lastindex = len(retdata['bookmarks']) - 1
                    elif min in bookmarkcont and max(tweetmins.values()) > 9: # Arbitrary value chosen for now - needs experimentation - was 9
                        retdata['bookmarks'][lastindex]['endseconds'] = min*60+playertimesec+60

        else:
            retdata['status'] = "ERROR"
        return retdata
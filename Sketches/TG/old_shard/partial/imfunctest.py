# -*- coding: utf-8 -*-

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
from partial import *
from PMouseEventHandling import *
from PartialMagnaDoodle import *

"""
Test case to confirm subclassing can't work this way:
(meta)partial's __new__ returns the base class instead
of the partial class, so no references are held to the partial
class at all: its name becomes an alias for the base class
"""
class ClickTest(partial, MouseEventHandler):
    
    @replace   # required
    def handleMouseUp(self, event):
        super(ClickPrint, self).handleMouseUp.im_func(self, event) # causes <type 'exceptions.AttributeError'>: 'NoneType' object has no attribute 'exc_info'
        #MouseEventHandler.handleMouseUp.im_func(self, event) # infinite loop
        print 'hup!'

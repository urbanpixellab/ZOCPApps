#/usr/bin/env python3
#
# ZOCP Video Player
# Copyright (c) 2014 Stichting z25.org
# Copyright (c) 2014 Arnaud Loonstra <arnaud@sphaero.org>
#
# ZOCP Video Player is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# Use the following pipeline for a sender:
# gst-launch-1.0 -v videotestsrc ! video/x-raw,frame-rate=10/1 ! x264enc speed-preset=1 tune=zero-latency byte-stream=true intra-refresh=true option-string="bframes=0:force-cfr:no-mbtree:sync-lookahead=0:sliced-threads:rc-lookahead=0" ! video/x-h264,profile=high ! rtph264pay config-interval=1 ! udpsink host=127.0.0.1 port=5000
#
# Debian dependencies:
# apt-get install gstreamer1.0-plugins-bad gstreamer1.0-plugins-good gstreamer1.0-tools python3-gst-1.0 gstreamer1.0-libav gir1.2-gstreamer-1.0 gir1.2-gst-plugins-base-1.0

import gi
gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst
print(Gst.version())

from zocp import ZOCP
import zmq
import socket


class GstZOCP(ZOCP):
    
    def __init__(self, *args, **kwargs):
        super(GstZOCP, self).__init__(*args, **kwargs)
        GObject.threads_init()
        self.loop = GObject.MainLoop()
        Gst.init(None)
        #"file:///home/people/arnaud/Videos/tordinaire-youtubeHD.mp4", 
        self.pls = "file:///home/pi/test3.h264,file:///home/pi/tordinaire-youtubeHD.mp4"
        #self.pls = "file:///home/people/arnaud/Videos/test.h264,file:///home/people/arnaud/Videos/test2.h264"
        self.count = 0
        # create elements
        self.pipeline = Gst.Pipeline()
        self.videosrc = Gst.ElementFactory.make('uridecodebin', 'videosrc0')
        self.glcolorconv = Gst.ElementFactory.make("glcolorscale", "glcolorconv0")
        self.glshader = Gst.ElementFactory.make("glshader", "glshader0")
        self.glimagesink = Gst.ElementFactory.make('glimagesink', "glimagesink0")
        self.sinkbin = Gst.Bin('sinkbin0')
        
        # setup the pipeline
        #videosrc.set_property("video-sink", glimagesink)
        self.videosrc.set_property("uri", self.pls.split(',')[self.count])
        #self.glimagesink.set_locked_state(True)
        self.sinkbin.add(self.glcolorconv)
        self.sinkbin.add(self.glshader)
        self.sinkbin.add(self.glimagesink)
        self.glshader.set_property("location", "shader.glsl")
        self.glshader.set_property("vars", "float alpha = float(1.);")
        self.glshader.set_property("preset", "preset.glsl")
        
        # we add a message handler
        self.bus = self.pipeline.get_bus()
        self.bus.add_watch(0, self.bus_call, self.loop) # 0 == GLib.PRIORITY_DEFAULT 
        
        # we add all elements into the pipeline
        self.pipeline.add(self.videosrc)
        self.pipeline.add(self.sinkbin)
        
        # we link the elements together
        self.glcolorconv.link(self.glshader)
        self.glshader.link(self.glimagesink)
        ghostpad = Gst.GhostPad.new("sink", self.glcolorconv.get_static_pad("sink"))
        self.sinkbin.add_pad(ghostpad)
        #videosrc.link(glimagesink)
        self.videosrc.connect("pad-added", self.on_pad_added, self.sinkbin)
        #self.videosrc.connect("drained", self.on_drained)

        self.set_name("zvidplyr@{0}".format(socket.gethostname()))
        self.register_bool("quit", False, access='rw')
        self.register_vec2f("top_left", (-1.0, 1.0), access='rw', step=[0.01, 0.01])
        self.register_vec2f('top_right', (1.0, 1.0), access='rw', step=[0.01, 0.01])
        self.register_vec2f('bottom_right', (1.0, -1.0), access='rw', step=[0.01, 0.01])
        self.register_vec2f('bottom_left', (-1.0, -1.0), access='rw', step=[0.01, 0.01])
        self.register_string("playlist", self.pls, access="rws")
        self.register_bool("fade", False, access="rws")
        self.register_vec3f("fade_color", (0,0,0), access="rws")
        self.register_bool("pause", False, access="rws")
        self.register_bool("stop", False, access="rws")
        
        self._fade_val = 1.0
    
    def pause_vid(self, p):
        if p:
            print("pause", p)
            self.pipeline.set_state(Gst.State.PAUSED)
        else:
            self.pipeline.set_state(Gst.State.PLAYING)

    def stop_vid(self, p):
        if p:
            self.pipeline.set_state(Gst.State.PAUSED)
            self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)
        else:
            self.pipeline.set_state(Gst.State.PLAYING)
     
    def fade_vid(self, f):
        if f and self._fade_val == 0.:
            GObject.timeout_add(10, self._fade, f)
        elif self._fade_val == 1.0:
            GObject.timeout_add(10, self._fade, f)        

    def bus_call(self, bus, msg, *args):
        """
        handling messages on the gstreamer bus
        """
        if msg.type == Gst.MessageType.EOS:
            self.update_uri()           # get next file from playlist
            return True
        elif msg.type == Gst.MessageType.ERROR:
            print(msg.parse_error())
            self.loop.quit()            # quit.... (better restart app?)
            return True
        return True

    def update_uri(self, *args, **kwargs):
        """
        set next file from playlist
        """
        pls = self.pls.split(',')
        self.count = (self.count+1)%len(pls)        
        self.pipeline.set_state(Gst.State.PAUSED)
        #self.glimagesink.set_state(Gst.State.PAUSED)
        next_vid = pls[self.count]
        print(next_vid)
        self.videosrc.set_property("uri", next_vid)
        # seek to beginning
        self.pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)
        
        self.pipeline.set_state(Gst.State.PLAYING)
        #self.glimagesink.set_state(Gst.State.PLAYING)
        return True

    def on_pad_added(self, element, pad, target, *args):
        """
        called when we can link to the sink
        """
        print(element, pad, target)
        if not pad.is_linked():
            pad.link(target.get_static_pad("sink")) #args[0])

    def zocp_handle(self, *args, **kwargs):
        self.run_once()
        if self.capability['quit']['value']:
            self.loop.quit()
        return True

    def on_modified(self, peer, name, data, *args, **kwargs):
        """
        Called when some data is modified on this node.
        peer: id of peer that made the change
        name: name of peer that made the change
        data: changed data, formatted as a partial capability dictionary, containing
              only the changed part(s) of the capability tree of the node
        """
        if self._running:
            for k,v in data.items():
                if k == "pause":
                    print(k,v.get('value'))
                    self.pause_vid(v.get('value'))
                elif k == "stop":
                    self.stop_vid(v.get('value'))
                elif k == "fade":
                    self.fade_vid(v.get('value'))
                else:
                    print("don't know", k, v)
        
    def emit_signal(self, emitter, data):
        super(GstZOCP, self).emit_signal(emitter, data)
        print("EMIT SIG:", emitter)
        if emitter == "pause":
            self.pause_vid(data)
        elif emitter == "stop":
            self.stop_vid(data)
        elif emitter == "fade":
            self.fade_vid(data)
    
    def run(self):
        # listen to the zocp inbox socket
        GObject.io_add_watch(
            self.inbox.getsockopt(zmq.FD), 
            GObject.PRIORITY_DEFAULT, 
            GObject.IO_IN, self.zocp_handle
        )
        #GObject.timeout_add(2000, self.update_uri)
        self.start()

        self.pipeline.set_state(Gst.State.PLAYING)
        #self.glimagesink.set_state(Gst.State.PLAYING)
        
        try:
            self.loop.run()
        except Exception as e:
            print(e)
        finally:
            self.stop()
        
        self.pipeline.set_state(Gst.State.NULL)

    def _fade(self, f):
        self.glshader.set_property("vars", "float alpha = float({0});".format(self._fade_val))
        if f:
            self._fade_val += 0.01
            if self._fade_val >= 1.0:
                self._fade_val = 1.0
                return False
        else:
            self._fade_val -= 0.01
            if self._fade_val <= .0:
                self._fade_val = .0
                return False
        print(self._fade_val)
        return True

if __name__ == "__main__":
    player = GstZOCP()
    player.run()

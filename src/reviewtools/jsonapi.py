#-*- coding: utf-8 -*-

#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.
#
# (C) 2011 - Stanislav Ochotnicky <sochotnicky@redhat.com>

'''
JSON API for FedoraReview plugins
'''
import subprocess
from json import JSONEncoder, JSONDecoder

from reviewtools import Helpers, TestResult


class JSONAPI(object):
    """Base class for all JSON plugin communication"""
    supported_api = 1


class SetupPlugin(JSONAPI):
    """First-contact API with plugin"""
    def __init__(self, spec, srpm, sources):
        self.pkgname = spec.name
        self.version = spec.version
        self.release = spec.release
        self.srpm = srpm.filename
        self.spec = {"path": spec.filename,
                     "text": spec.get_expanded()}
        self.rpms = []
        for rpm in srpm.get_files_rpms().keys():
            self.rpms.append(rpm)
        self.rpmlint = "\n".join(srpm.rpmlint_output)
        self.build_dir = srpm.get_build_dir()


class GetSectionReply(JSONAPI):
    """Reply to get_section JSON command"""
    def __init__(self, section_text):
        self.text = section_text


class ErrorReply(JSONAPI):
    """Reply used when we encounter error in processing the request

    This is usually caused by unknown call
    """
    def __init__(self, error_text):
        self.error = error_text


class PluginResponse(JSONAPI):
    """Class for plugin responses"""
    command = None


class JSONPlugin(Helpers):
    """Plugin for communicating with external review checks using JSON"""

    def __init__(self, base, plugin_path):
        Helpers.__init__(self)
        self.plugin_path = plugin_path
        self.spec = base.spec
        self.srpm = base.srpm
        self.sources = base.sources
        self.encoder = ReviewJSONEncoder()
        self.decoder = JSONDecoder()
        self.results = []
        self.plug_in = None
        self.plug_out = None
        self.plug_err = None

    def run(self):
        """Run the plugin to produce results"""
        plugin_proc = subprocess.Popen(self.plugin_path,
                                       bufsize=-1,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       stdin=subprocess.PIPE)
        self.plug_in = plugin_proc.stdin
        self.plug_out = plugin_proc.stdout
        self.plug_err = plugin_proc.stderr

        setup = SetupPlugin(self.spec, self.srpm, self.sources)
        self.__send_obj(setup)

        final_data = ""
        while True:
            data = plugin_proc.stdout.readline()
            if data == "":
                break
            final_data = final_data + data
            obj = self.__get_class_from_json(final_data)
            if obj:
                self.__handle_reply(obj)
                final_data = ""

        errout = self.plug_err.read()
        while errout != "":
            self.log.debug("ERROR: %s: %s" % (self.plugin_path, errout))
            errout = self.plug_err.read()


    def get_results(self):
        """Returns array of results

        get_result() -> [TestResult, TestResult, ...]"""
        return self.results

    def __get_class_from_json(self, text):
        """Convert JSON reply to simple Python object

        returns None if JSON cannot be decoded
        """
        ret = None
        try:
            json_obj = self.decoder.decode(text)
            ret = PluginResponse()
            for key in json_obj.keys():
                setattr(ret, key, json_obj[key])
            if not hasattr(ret, "command"):
                self.log.error("Error: plugin returned JSON object without 'command' ")
                # Reply has to have this
                return None
        except ValueError:
            # ret is set to None
            pass
        return ret

    def __handle_reply(self, reply):
        """Handle incomming commands and results"""
        if reply.command == "results":
            for result in reply.checks:
                extra = None
                if "output_extra" in result:
                    extra = result["output_extra"]
                self.results.append(TestResult(result["name"],
                                               result["url"],
                                               result["group"],
                                               result["deprecates"],
                                               result["text"],
                                               result["type"],
                                               result["result"], extra))
        elif reply.command == "get_section":
            sec_name = "%%%s" % reply.section
            gs_ret = self.spec.get_section(sec_name)
            if sec_name not in gs_ret:
                section_text = ""
                self.log.debug("Plugin %s asked for non-existent"
                               "section %s" % (self.plugin_path,
                                               sec_name))
            else:
                section_text = "\n".join(gs_ret[sec_name])
            msg = GetSectionReply(section_text)
            self.__send_obj(msg)
        else:
            self.log.debug("Received unrecognized message command %s from"
                           "plugin %s" % (reply.command, self.plugin_path))
            self.__send_obj(ErrorReply("Unrecognized command %s" % reply.command))

    def __send_obj(self, obj):
        """Send JSONAPI subclass to JSON plugin"""
        self.plug_in.write(self.encoder.encode(obj))
        self.plug_in.write("\n\n")
        self.plug_in.flush()


class ReviewJSONEncoder(JSONEncoder):
    """Custom JSON encoder for JSONAPI subclasses"""
    IGNORED = ['__module__', '__dict__', '__doc__', '__init__', '__weakref__',
             '__slots__']

    def default(self, encclass):
        if not isinstance(encclass, JSONAPI):
            print 'You cannot use the ReviewJSONEmcoder for a non-JSONAPI object.'
            return
        ret = {}
        # get things from base classes
        for base in encclass.__class__.__bases__:
            if hasattr(base, "__dict__"):
                for item in base.__dict__:
                    ret[item] = base.__dict__[item]

        # get things defined in class
        for item in encclass.__class__.__dict__:
            ret[item] = encclass.__class__.__dict__[item]

        # instance variables
        if hasattr(encclass, "__dict__"):
            for item in encclass.__dict__:
                ret[item] = encclass.__dict__[item]

        # slot variables
        if hasattr(encclass, "__slots__"):
            for item in encclass.__slots__:
                ret[item] = getattr(encclass, item)

        for rem in self.IGNORED:
            if rem in ret:
                ret.pop(rem)

        return ret
# Microsoft Azure Linux Agent
#
# Copyright 2014 Microsoft Corporation
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
#
# Requires Python 2.4+ and Openssl 1.0+
#
"""
Copy and parse ovf-env.xml from provisioning ISO and local cache
"""
import os
import re
import shutil
import xml.dom.minidom as minidom
import azurelinuxagent.logger as logger
from azurelinuxagent.future import text
import azurelinuxagent.utils.fileutil as fileutil
from azurelinuxagent.utils.textutil import parse_doc, findall, find, findtext
from azurelinuxagent.utils.osutil import OSUTIL, OSUtilError
from azurelinuxagent.protocol.common import ProtocolError

OVF_FILE_NAME = "ovf-env.xml"

#Tag file to indicate usage of metadata protocol
TAG_FILE_NAME = "useMetadataEndpoint.tag" 

OVF_VERSION = "1.0"
OVF_NAME_SPACE = "http://schemas.dmtf.org/ovf/environment/1"
WA_NAME_SPACE = "http://schemas.microsoft.com/windowsazure"

def get_ovf_env():
    """
    Load saved ovf-env.xml
    """
    ovf_file_path = os.path.join(OSUTIL.get_lib_dir(), OVF_FILE_NAME)
    if os.path.isfile(ovf_file_path):
        xml_text = fileutil.read_file(ovf_file_path)
        return OvfEnv(xml_text)
    else:
        raise ProtocolError("ovf-env.xml is missing.")

def copy_ovf_env():
    """
    Copy ovf env file from dvd to hard disk.
    Remove password before save it to the disk
    """
    try:
        OSUTIL.mount_dvd()

        ovf_file_path_on_dvd = OSUTIL.get_ovf_env_file_path_on_dvd()
        ovfxml = fileutil.read_file(ovf_file_path_on_dvd, remove_bom=True)
        ovfenv = OvfEnv(ovfxml)
        ovfxml = re.sub("<UserPassword>.*?<", "<UserPassword>*<", ovfxml)
        ovf_file_path = os.path.join(OSUTIL.get_lib_dir(), OVF_FILE_NAME)
        fileutil.write_file(ovf_file_path, ovfxml)
        
        tag_file_path_on_dvd = os.path.join(OSUTIL.get_dvd_mount_point(),
                                            TAG_FILE_NAME)
        if os.path.isfile(tag_file_path_on_dvd):
            logger.info("Found {0} in provisioning ISO", TAG_FILE_NAME)
            tag_file_path = os.path.join(OSUTIL.get_lib_dir(), TAG_FILE_NAME)
            shutil.copyfile(tag_file_path_on_dvd, tag_file_path) 

        OSUTIL.umount_dvd()
        OSUTIL.eject_dvd()
    except IOError as e:
        raise ProtocolError(text(e))
    except OSUtilError as e:
        raise ProtocolError(text(e))
    return ovfenv

def _validate_ovf(val, msg):
    if val is None:
        raise ProtocolError("Failed to parse OVF XML: {0}".format(msg))

class OvfEnv(object):
    """
    Read, and process provisioning info from provisioning file OvfEnv.xml
    """
    def __init__(self, xml_text):
        if xml_text is None:
            raise ValueError("ovf-env is None")
        logger.verb("Load ovf-env.xml")
        self.hostname = None
        self.username = None
        self.user_password = None
        self.customdata = None
        self.disable_ssh_password_auth = True
        self.ssh_pubkeys = []
        self.ssh_keypairs = []
        self.parse(xml_text)

    def parse(self, xml_text):
        """
        Parse xml tree, retreiving user and ssh key information.
        Return self.
        """
        wans = WA_NAME_SPACE
        ovfns = OVF_NAME_SPACE

        xml_doc = parse_doc(xml_text)
        
        environment = find(xml_doc, "Environment", namespace=ovfns)
        _validate_ovf(environment, "Environment not found")

        section = find(environment, "ProvisioningSection", namespace=wans)
        _validate_ovf(section, "ProvisioningSection not found")

        version = findtext(environment, "Version", namespace=wans)
        _validate_ovf(version, "Version not found")

        if version > OVF_VERSION:
            logger.warn("Newer provisioning configuration detected. "
                        "Please consider updating waagent")
        
        conf_set = find(section, "LinuxProvisioningConfigurationSet", 
                        namespace=wans)
        _validate_ovf(conf_set, "LinuxProvisioningConfigurationSet not found")

        self.hostname = findtext(conf_set, "HostName", namespace=wans)
        _validate_ovf(self.hostname, "HostName not found")

        self.username = findtext(conf_set, "UserName", namespace=wans)
        _validate_ovf(self.username, "UserName not found")
        
        self.user_password = findtext(conf_set, "UserPassword", namespace=wans)

        self.customdata = findtext(conf_set, "CustomData", namespace=wans)
        
        auth_option = findtext(conf_set, "DisableSshPasswordAuthentication", 
                               namespace=wans)
        if auth_option is not None and auth_option.lower() == "true":
            self.disable_ssh_password_auth = True
        else:
            self.disable_ssh_password_auth = False

        public_keys = findall(conf_set, "PublicKey", namespace=wans)
        for public_key in public_keys:
            path = findtext(public_key, "Path", namespace=wans)
            fingerprint = findtext(public_key, "Fingerprint", namespace=wans)
            value = findtext(public_key, "Value", namespace=wans)
            self.ssh_pubkeys.append((path, fingerprint, value))

        keypairs = findall(conf_set, "KeyPair", namespace=wans)
        for keypair in keypairs:
            path = findtext(keypair, "Path", namespace=wans)
            fingerprint = findtext(keypair, "Fingerprint", namespace=wans)
            self.ssh_keypairs.append((path, fingerprint))


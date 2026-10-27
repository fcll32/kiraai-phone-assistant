"""Reject APKs missing the uni-app page, native control bridge, or Android services."""
import argparse
from pathlib import Path
import struct
import zipfile


def classes(dex):
    def integer(offset):
        return struct.unpack_from('<I', dex, offset)[0]
    strings_count, strings_offset = integer(56), integer(60)
    strings = []
    for index in range(strings_count):
        offset = integer(strings_offset + index * 4)
        while dex[offset] & 128:
            offset += 1
        offset += 1
        end = dex.index(b'\0', offset)
        strings.append(dex[offset:end].decode('utf-8', errors='replace'))
    types = [strings[integer(integer(68) + index * 4)] for index in range(integer(64))]
    return {types[integer(integer(100) + index * 32)] for index in range(integer(96))}


def verify(path):
    with zipfile.ZipFile(path) as apk:
        if apk.testzip() is not None:
            raise ValueError('Corrupt APK')
        required = {
            'assets/apps/__UNI__KIRAPHONE/www/app-service.js',
            'assets/apps/__UNI__KIRAPHONE/www/bytes/GenPagesIndexIndexSharedData.kt.bytes',
            'assets/licenses/Java-WebSocket-LICENSE.txt',
            'assets/licenses/SLF4J-LICENSE.txt',
        }
        if not required.issubset(apk.namelist()):
            raise ValueError('Missing app resources: ' + str(required.difference(apk.namelist())))
        all_classes = set()
        for name in apk.namelist():
            if name.startswith('classes') and name.endswith('.dex'):
                all_classes.update(classes(apk.read(name)))
        expected = {
            'Ltop/kira/phone/PhoneRuntime;', 'Ltop/kira/phone/ConnectionService;',
            'Ltop/kira/phone/PhoneAccessibility;', 'Ltop/kira/phone/CommandGate;',
            'Ltop/kira/phone/VoiceRuntime;', 'Ltop/kira/phone/VoiceCallService;',
            'Ltop/kira/phone/SocketSecurity;', 'Ltop/kira/phone/VoiceVad;',
            'Ltop/kira/phone/VirtualMicRuntime;', 'Ltop/kira/phone/VirtualMicService;',
            'Ltop/kira/phone/VirtualMicSignal;', 'Lrikka/shizuku/ShizukuProvider;',
            'Luts/sdk/modules/kiraPhone/IndexKt;', 'Luts/sdk/modules/kiraPhone/UniUTSMethodRegister;',
            'Lio/dcloud/uts/generated/StaticUTSAutoRegister;', 'Lio/dcloud/uniappxv/UniAppActivity;',
            'Lio/dcloud/uts/generated/module/UtsSdkModulesKiraPhoneAutoRegister;',
            # uni.showModal resolves the official _uni-modal module at runtime.
            'Luts/sdk/modules/DCloudUniModal/IndexKt;',
            'Luts/sdk/modules/DCloudUniModal/UniUTSMethodRegister;',
            'Lio/dcloud/uts/generated/module/IoDcloudUtsUniModalAutoRegister;',
        }
        if not expected.issubset(all_classes):
            raise ValueError('Missing compiled bridge/services: ' + str(expected.difference(all_classes)))
        return len(all_classes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    args = parser.parse_args()
    print(f'Verified uni-app resources, control bridge and services among {verify(args.apk)} DEX classes')

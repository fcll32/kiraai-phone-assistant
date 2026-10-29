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


def xml_strings(data):
    """Read the string pool of compiled Android XML, including optimized paths."""
    if len(data) < 8 or struct.unpack_from('<H', data)[0] != 3:
        return set()
    position = struct.unpack_from('<H', data, 2)[0]
    while position + 8 <= len(data):
        kind, header, size = struct.unpack_from('<HHI', data, position)
        if size < header or size < 8 or position + size > len(data):
            raise ValueError('Invalid compiled Android XML')
        if kind == 1:
            count, _, flags, start, _ = struct.unpack_from('<IIIII', data, position + 8)
            result = set()
            def length(offset, unit):
                value = data[offset] if unit == 1 else struct.unpack_from('<H', data, offset)[0]
                marker = 0x80 if unit == 1 else 0x8000
                if value & marker:
                    following = data[offset + unit] if unit == 1 else struct.unpack_from('<H', data, offset + unit)[0]
                    return ((value & (marker - 1)) << (unit * 8)) | following, offset + unit * 2
                return value, offset + unit
            for index in range(count):
                offset = position + start + struct.unpack_from('<I', data, position + header + index * 4)[0]
                if flags & 0x100:
                    _, offset = length(offset, 1)
                    size_bytes, offset = length(offset, 1)
                    result.add(data[offset:offset + size_bytes].decode('utf-8'))
                else:
                    characters, offset = length(offset, 2)
                    result.add(data[offset:offset + characters * 2].decode('utf-16-le'))
            return result
        position += size
    return set()


def verify(path):
    with zipfile.ZipFile(path) as apk:
        if apk.testzip() is not None:
            raise ValueError('Corrupt APK')
        required = {
            'assets/apps/__UNI__KIRAPHONE/www/app-service.js',
            'assets/apps/__UNI__KIRAPHONE/www/static/kira-wallpaper.jpg',
            'assets/apps/__UNI__KIRAPHONE/www/static/companions/hello.png',
            'assets/apps/__UNI__KIRAPHONE/www/static/companions/connected.png',
            'assets/apps/__UNI__KIRAPHONE/www/static/companions/call.png',
            'assets/apps/__UNI__KIRAPHONE/www/bytes/GenPagesIndexIndexSharedData.kt.bytes',
            'assets/licenses/Java-WebSocket-LICENSE.txt',
            'assets/licenses/SLF4J-LICENSE.txt',
        }
        artwork = {
            'companions': ('hello', 'connected', 'call', 'device', 'link', 'guide', 'about', 'rest', 'shield'),
            'scenes': ('device', 'connection', 'voice', 'guide', 'about', 'menu'),
        }
        for directory, names in artwork.items():
            required.update(f'assets/apps/__UNI__KIRAPHONE/www/static/{directory}/{name}.png' for name in names)
        if not required.issubset(apk.namelist()):
            raise ValueError('Missing app resources: ' + str(required.difference(apk.namelist())))
        # AGP optimizes resource names (e.g. res/Ab.xml); inspect compiled XML
        # instead of requiring its original source filename in the ZIP.
        provider = {'paths', 'external-files-path', 'updates', 'Download/updates/'}
        if not any(provider.issubset(xml_strings(apk.read(name))) for name in apk.namelist()
                   if name.startswith('res/') and name.endswith('.xml')):
            raise ValueError('Missing restricted update APK FileProvider paths')
        manifest = xml_strings(apk.read('AndroidManifest.xml'))
        if not {'top.kira.phone.UpdateRuntime$ApkProvider', 'top.kira.phone.updates',
                'android.permission.REQUEST_INSTALL_PACKAGES'}.issubset(manifest):
            raise ValueError('Missing update provider or install permission')
        all_classes = set()
        for name in apk.namelist():
            if name.startswith('classes') and name.endswith('.dex'):
                all_classes.update(classes(apk.read(name)))
        expected = {
            'Ltop/kira/phone/UpdatePolicy;', 'Ltop/kira/phone/UpdateRuntime;',
            'Ltop/kira/phone/UpdateRuntime$ApkProvider;',
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
            'Luts/sdk/modules/DCloudUniVibrate/IndexKt;',
            'Luts/sdk/modules/DCloudUniVibrate/UniUTSMethodRegister;',
            'Lio/dcloud/uts/generated/module/IoDcloudUtsUniVibrateAutoRegister;',
        }
        if not expected.issubset(all_classes):
            raise ValueError('Missing compiled bridge/services: ' + str(expected.difference(all_classes)))
        return len(all_classes)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('apk', type=Path)
    args = parser.parse_args()
    print(f'Verified uni-app resources, control bridge and services among {verify(args.apk)} DEX classes')

// #ifdef APP-ANDROID
import * as native from '@/uni_modules/kira-phone'
// #endif

const unavailable = () => { throw new Error('网页仅供界面预览，请在 Android APK 中连接手机') }
let previewShield = true
let adapter = {
  readState: () => JSON.stringify({ running: false, connected: false, configured: false,
    accessibility: false, status: '网页界面预览', sdk: 30, deviceName: 'Android 手机',
    deviceId: '', address: '', version: '1.1.6', reducedMotion: false, animationSpeed: 1,
    screenProtected: previewShield, secureConfigured: true }),
  readConfig: () => JSON.stringify({ address: '', password: '', fingerprint: '' }),
  readCallState: () => JSON.stringify({ active: false, status: 'idle', microphoneGranted: false, muted: false, speaker: true, level: 0, transcripts: [], detail: '网页仅预览界面，请在手机上开始通话。' }),
  readVirtualMicState: () => JSON.stringify({ supported: false, authorized: false, active: false, verified: false, detail: '请在 Android 手机上检测 Shizuku 和系统兼容性。' }),
  requestMicrophone: unavailable, startCall: unavailable, stopCall: unavailable,
  setCallMuted: unavailable, setCallSpeaker: unavailable, interruptCall: unavailable,
  authorizeVirtualMic: unavailable, testVirtualMic: unavailable, stopVirtualMic: unavailable,
  saveConfig: unavailable, startConnection: unavailable, stopConnection: unavailable,
  openAccessibility: unavailable, prepare() {}, secure() {},
  setSecure(enabled) { previewShield = enabled; return enabled }, savePreferences() {}, reveal() {}
}
// #ifdef APP-ANDROID
adapter = native
// #endif

export const phone = adapter
export function errorText(error) {
  const message = error && error.message ? error.message : String(error)
  return message.replace(/^.*?(?:IllegalArgumentException|IllegalStateException):\s*/, '')
}

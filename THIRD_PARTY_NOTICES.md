# Third-party notices

The Android APK uses the uni-app x Vapor 5.26 Android runtime and its required Android libraries, in addition to Java-WebSocket 1.5.7 and SLF4J 2.0.16 and Shizuku API/provider 13.1.5.

- Java-WebSocket: https://github.com/TooTallNate/Java-WebSocket/tree/v1.5.7 — MIT license, copyright Nathan Rajlich.
- Shizuku API/provider: https://github.com/RikkaApps/Shizuku-API — MIT license, copyright RikkaW. The manager app is installed separately by the user.
- SLF4J: https://www.slf4j.org/license.html — MIT license, copyright QOS.ch.

The full Java-WebSocket, SLF4J and Shizuku API notices are included in `third-party/` and in the APK under `assets/licenses/`.

The DCloud SDK is downloaded from its official distribution, is not part of this source archive, and remains subject to its own terms: https://doc.dcloud.net.cn/uni-app-x/native/download/android.html . This project does not relicense the DCloud runtime.

The offline Android build declares AndroidX, Material Components, Kotlin and coroutines, Fresco, AndroidSVG, Fastjson, XXPermissions and OkHttp in `uni-app/native-android/app/build.gradle`. Their original licenses apply. SDK advertising, recording, location and payment modules are not included.
KiraAI itself is a separate dependency and is not included in this source distribution.

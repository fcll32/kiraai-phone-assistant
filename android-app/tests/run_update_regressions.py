"""Run actual update policy and the production HTTPS reader on the JVM.

This models Android package identity data; device DownloadManager/installer UI
still requires a phone. --live also reads the public GitHub release endpoint.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "android-app/app/src/main/java/top/kira/phone"


def method(text, signature):
    start = text.index(signature)
    brace = text.index("{", start)
    end, depth = brace + 1, 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[start:end]


def main(live=False):
    java_home = Path(os.environ.get("JAVA_HOME", ROOT / ".runtime/jdk21/jdk-21.0.12.1+1"))
    suffix = ".exe" if os.name == "nt" else ""
    def tool(name):
        local = java_home / "bin" / (name + suffix)
        return str(local) if local.is_file() else shutil.which(name)
    reader = method((SOURCE / "UpdateRuntime.java").read_text(encoding="utf-8"), "private static String fetch(")
    quiet = method((SOURCE / "UpdateRuntime.java").read_text(encoding="utf-8"), "public static void checkQuietly(").replace('android.os.SystemClock.elapsedRealtime()', 'clock')
    code = r'''
package top.kira.phone;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.security.MessageDigest;
import java.util.concurrent.TimeUnit;
public class UpdateBoundaryTest {
 static volatile HttpURLConnection connection;
 static boolean allowed = true;
 static boolean current(long ticket) { return allowed; }
 static final Object LOCK = new Object();
 static final ArrayDeque<Runnable> pending = new ArrayDeque<>();
 static final java.util.concurrent.Executor WORK = pending::add;
 static class Context { }
 static Object release;
 static long lastQuietCheck=-1,clock;
 static boolean restoring,busyFlag;
 static int requested;
 static void ensure(Context context) { if(restoring) { restoring=false; pending.add(()->release=new Object()); } }
 static boolean busy() { return busyFlag; }
 static void check(Context context) { requested++; }
 static void drain() { while(!pending.isEmpty())pending.remove().run(); }
 static int checks;
 static void require(boolean ok) { checks++; if(!ok) throw new AssertionError(); }
 interface Throwing { void run() throws Exception; }
 static void rejects(Throwing action) throws Exception {
   checks++; try { action.run(); throw new AssertionError("accepted invalid update"); }
   catch(IllegalArgumentException | InterruptedException expected) { }
 }
 static void identity(String pkg, String version, long code, int sdk, Set<String> cert) {
   UpdatePolicy.verifyIdentity("top.kira.phone","1.0.1",1,pkg,version,code,26,sdk,Set.of("publisher"),cert);
 }
 public static void main(String[] args) throws Exception {
   Context context=new Context();restoring=true;checkQuietly(context);drain();
   require(requested==0); // Restored download metadata must survive startup.
   release=null;busyFlag=true;checkQuietly(context);drain();require(requested==0);
   busyFlag=false;checkQuietly(context);drain();require(requested==1);
   clock=TimeUnit.HOURS.toMillis(5);checkQuietly(context);drain();require(requested==1);
   clock=TimeUnit.HOURS.toMillis(6);checkQuietly(context);drain();require(requested==2);
   release=new Object();clock=TimeUnit.HOURS.toMillis(12);checkQuietly(context);drain();require(requested==2);
   require(UpdatePolicy.compare("v1.10.0","1.9.99")>0);
   require(UpdatePolicy.compare("1.0.0","1.0.0")==0);
   require(UpdatePolicy.compare("1.0.1","1.1.0")<0);
   rejects(()->UpdatePolicy.version("1.0.1-beta"));
   rejects(()->UpdatePolicy.version("1.0.12345678901234"));
   rejects(()->UpdatePolicy.repository("owner/../repo"));
   String repo="fcll32/kiraai-phone-assistant", tag="v1.0.1", name=UpdatePolicy.apkName(tag);
   String url="https://github.com/"+repo+"/releases/download/"+tag+"/"+name;
   require(UpdatePolicy.assetUrl(repo,tag,name,url).equals(url));
   for(String invalid:List.of(url.replace("https:","http:"),url.replace("github.com","github.com.evil.test"),url+"?redirect=1",url+"#x",url.replace("github.com","user@github.com"),url.replace("fcll32","someone"),url.replace("v1.0.1/","v1.0.2/")))
     rejects(()->UpdatePolicy.assetUrl(repo,tag,name,invalid));
   String hash="a".repeat(64);
   require(UpdatePolicy.digest("sha256:"+hash).equals(hash));
   require(UpdatePolicy.checksum(hash+"  "+name+"\n",name).equals(hash));
   rejects(()->UpdatePolicy.checksum(hash+"  other.apk\n",name));
   rejects(()->UpdatePolicy.checksum(hash+"  "+name+"\n"+hash+"  "+name,name));
   rejects(()->UpdatePolicy.digest("md5:"+hash));
   rejects(()->UpdatePolicy.size(0)); rejects(()->UpdatePolicy.size(UpdatePolicy.MAX_APK_BYTES+1));
   identity("top.kira.phone","1.0.1",2,26,Set.of("publisher")); checks++;
   rejects(()->identity("other.app","1.0.1",2,26,Set.of("publisher")));
   rejects(()->identity("top.kira.phone","1.0.2",2,26,Set.of("publisher")));
   rejects(()->identity("top.kira.phone","1.0.1",1,26,Set.of("publisher")));
   rejects(()->identity("top.kira.phone","1.0.1",2,25,Set.of("publisher")));
   rejects(()->identity("top.kira.phone","1.0.1",2,26,Set.of("different")));
   rejects(()->identity("top.kira.phone","1.0.1",2,26,Set.of()));
   Path path=Files.createTempFile("kira-update-policy-",".apk");
   try {
     byte[] bytes="fixture package, not an installable APK".getBytes(StandardCharsets.UTF_8);
     Files.write(path,bytes);
     String real=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
     UpdatePolicy.verifyFile(path.toFile(),bytes.length,real,()->true); checks++;
     rejects(()->UpdatePolicy.verifyFile(path.toFile(),bytes.length+1,real,()->true));
     rejects(()->UpdatePolicy.verifyFile(path.toFile(),bytes.length,hash,()->true));
     rejects(()->UpdatePolicy.verifyFile(path.toFile(),bytes.length,real,()->false));
   } finally { Files.deleteIfExists(path); }
   rejects(()->fetch("http://api.github.com/repos/"+repo+"/releases/latest",0));
   rejects(()->fetch("https://evil.test/updates",0));
   allowed=false; rejects(()->fetch("https://api.github.com/repos/"+repo+"/releases/latest",0)); allowed=true;
   if(args.length>0) {
     String metadata=fetch("https://api.github.com/repos/"+repo+"/releases/latest",0);
     require(metadata.contains("KiraAI-Phone-Assistant-"));
     require(metadata.contains("sha256:"));
     System.out.println("Production HTTPS reader reached public GitHub release metadata.");
   }
   System.out.println(checks+" update boundary checks passed.");
 }
 __READER__
 __QUIET__
}
'''.replace("__READER__", reader).replace("__QUIET__", quiet)
    with tempfile.TemporaryDirectory(prefix="kira-update-") as temporary:
        folder = Path(temporary)
        test = folder / "UpdateBoundaryTest.java"
        test.write_text(code, encoding="utf-8")
        subprocess.run([tool("javac"), "-encoding", "UTF-8", "-d", temporary,
                        str(SOURCE / "UpdatePolicy.java"), str(test)], check=True)
        subprocess.run([tool("java"), "-cp", temporary, "top.kira.phone.UpdateBoundaryTest"] + (["live"] if live else []), check=True, timeout=60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    main(parser.parse_args().live)

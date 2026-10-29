"""Run current production method bodies with explicit Android boundary stubs."""
from pathlib import Path
import subprocess
import os
import shutil

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '.runtime/runtime-regression'
OUT.mkdir(parents=True, exist_ok=True)
SRC = ROOT / 'android-app/app/src/main/java/top/kira/phone'
JAVA = Path(os.environ['JAVA_HOME']) / 'bin' if os.environ.get('JAVA_HOME') else ROOT / '.runtime/jdk21/jdk-21.0.12.1+1/bin'
JAVAC = str(JAVA/'javac.exe') if (JAVA/'javac.exe').exists() else shutil.which('javac')
JAVA_RUN = str(JAVA/'java.exe') if (JAVA/'java.exe').exists() else shutil.which('java')

def method(file, signature):
    text = (SRC / file).read_text(encoding='utf-8')
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]

code = '''import java.util.*;
public class AndroidBoundaryRepro {
 static class SharedPreferences {
  Map<String,String> data = new HashMap<>();
  String getString(String k,String d){return data.getOrDefault(k,d);}
  boolean getBoolean(String k,boolean d){return data.containsKey(k)?Boolean.parseBoolean(data.get(k)):d;}
  SharedPreferences edit(){return this;}
  SharedPreferences putString(String k,String v){data.put(k,v);return this;}
  boolean commit(){return true;}
 }
 static class Context { SharedPreferences settings = new SharedPreferences(); }
 static class Activity extends Context { int starts; void startForegroundService(Intent i){ starts++; } }
 static class Intent { Intent(Activity a,Class<?> c){} }
 static class ConnectionService { static boolean running; }
 static class PhoneAccessibility { static Object instance = new Object(); }
 static class VirtualMicRuntime { static boolean isActive(){return false;} }
 static class VoiceRuntime {
  static final Object AUDIO_LOCK = new Object(); static boolean active;
  static boolean isActive(){return active;}
  static void welcome(Object o){} static void update(Object o,String s,String m){}
  static void transcript(Object o,String r,String s){}
 }
 static SharedPreferences prefs(Context c){return c.settings;}
'''
code += method('PhoneRuntime.java', 'public static void save(')
code += method('PhoneRuntime.java', 'private static String[] validateConfig(')
code += method('PhoneRuntime.java', 'public static void start(')
code += method('PhoneRuntime.java', 'private static boolean screenProtected(')
code += method('PhoneRuntime.java', 'public static void secure(Activity activity)')
code += '''
 static boolean appliedSecure;
 static boolean applySecure(Activity a,boolean enabled,boolean persist){appliedSecure=enabled;return enabled;}
'''
code += '''
 static class JSONObject {
  Map<String,String> data = new HashMap<>();
  JSONObject(String... values){for(int i=0;i<values.length;i+=2)data.put(values[i],values[i+1]);}
  String optString(String k){return optString(k, "");}
  String optString(String k,String d){return data.getOrDefault(k,d);}
  int optInt(String k,int d){return d;}
 }
 static class SystemClock {static long elapsedRealtime(){return 0;}}
 static class Call {
  boolean active=true,welcomed=true,listening=false;
  String interruptId="",currentTurn="new-turn",failure="";
  Object turnLock=new Object(); long captureGeneration,quietUntil; Thread captureThread;
  void fail(String s){failure=s;active=false;}
  void finish(String s,String m){active=false;}
  void updateListening(){} void captureLoop(){} void send(JSONObject o){}
  JSONObject json(String... v){return new JSONObject(v);}
'''
code += method('VoiceCallService.java', 'private void message(')
code += '''
 }
 public static void main(String[] args) {
  Activity a=new Activity();
  if(screenProtected(a.settings))throw new AssertionError("Fresh privacy protection must default off");
  secure(a);if(appliedSecure)throw new AssertionError("Fresh activity must allow screenshots");
  a.settings.putString("screen_protected","true");secure(a);
  if(!screenProtected(a.settings)||!appliedSecure)throw new AssertionError("Saved enabled preference must survive");
  a.settings.putString("screen_protected","false");secure(a);
  if(screenProtected(a.settings)||appliedSecure)throw new AssertionError("Saved disabled preference must survive");
  System.out.println("PASS: default privacy off and both saved choices restored");
  a.settings.putString("url","wss://127.0.0.1:8443/ws/plugin/phone_control/device")
   .putString("token","MyKira88").putString("pin","");
  VoiceRuntime.active=true;
  start(a);
  if(a.starts!=1)throw new AssertionError("Control must start during a call");
  try {save(a,"127.0.0.1:8443","changed8","");throw new AssertionError("Configuration mutation must remain blocked");}
  catch(IllegalStateException expected){}
  VoiceRuntime.active=false;start(a);
  if(a.starts!=2)throw new AssertionError();
  a.settings.putString("token","bad");
  try {start(a);throw new AssertionError("Invalid settings must be rejected");}catch(IllegalArgumentException expected){}
  if(a.starts!=2)throw new AssertionError();
  System.out.println("PASS: both start orders; mutations and invalid settings rejected");
  Call c=new Call(); c.message(new JSONObject("type","error","id","new-turn","message","没有听清，请再说一次"));
  if(!c.active)throw new AssertionError("Recoverable error must keep call alive");
  c.message(new JSONObject("type","state","id","new-turn","state","listening"));
  if(!c.listening)throw new AssertionError();
  Call old=new Call();old.message(new JSONObject("type","error","id","old-turn","message","old error"));
  if(!old.active)throw new AssertionError("Stale error must be ignored");
  old.interruptId="interrupt";old.message(new JSONObject("type","error","id","new-turn","message","cancelled"));
  if(!old.active)throw new AssertionError();
  Call fatal=new Call();fatal.message(new JSONObject("type","error","message","protocol failure"));
  if(fatal.active)throw new AssertionError("Unscoped error must be fatal");
  Call auth=new Call();auth.welcomed=false;auth.message(new JSONObject("type","error","id","new-turn","message","auth failure"));
  if(auth.active)throw new AssertionError("Pre-auth error must be fatal");
  Call control=new Call();control.message(new JSONObject("type","transcript","id","old-turn","role","user","text","ignored"));
  if(!control.active)throw new AssertionError();
  System.out.println("PASS: current, stale, interrupted, authentication and protocol voice errors");
 }
}
'''
for name in ('ServerAddress', 'ConnectionPassword'):
    code += '\n' + (SRC / (name+'.java')).read_text(encoding='utf-8').split('\n',1)[1].replace('public final class','final class')
# Their imports must precede all classes.
lines=code.splitlines()
imports=[x for x in lines if x.startswith('import ')]
code='\n'.join(imports+[x for x in lines if not x.startswith('import ')])
(OUT/'AndroidBoundaryRepro.java').write_text(code,encoding='utf-8')
subprocess.run([JAVAC,'-encoding','UTF-8','-d',str(OUT),str(OUT/'AndroidBoundaryRepro.java')],check=True,timeout=30)
subprocess.run([JAVA_RUN,'-Dstdout.encoding=UTF-8','-cp',str(OUT),'AndroidBoundaryRepro'],check=True,timeout=15)

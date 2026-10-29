"""Exercise production control code on the JVM with explicit Android boundaries.

These checks model buffers, callbacks, nodes and editable text; they do not
claim device latency, screenshot quality or Android/OEM compatibility.
"""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "android-app/app/src/main/java/top/kira/phone"


def source_block(text, signature, *, body=False):
    start = text.index(signature)
    brace = text.index("{", start)
    end, depth = brace + 1, 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[brace + 1:end - 1] if body else text[start:end]


def main():
    java_home = os.environ.get("JAVA_HOME")
    java_bin = Path(java_home) / "bin" if java_home else ROOT / ".runtime/jdk21/jdk-21.0.12.1+1/bin"
    suffix = ".exe" if os.name == "nt" else ""
    def tool(name):
        local = java_bin / (name + suffix)
        found = str(local) if local.is_file() else shutil.which(name)
        if not found:
            raise SystemExit("JDK required: set JAVA_HOME")
        return found
    source = (SOURCE / "PhoneAccessibility.java").read_text(encoding="utf-8")
    code = r'''
package top.kira.phone;
import java.io.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.function.*;
public class ControlBoundaryRepro {
 static void require(boolean ok, String message) { if (!ok) throw new AssertionError(message); }
 static class JSONObject {
  final Map<String,Object> values = new HashMap<>();
  JSONObject put(String key, Object value) { values.put(key,value); return this; }
  int getInt(String key) { return ((Number)values.get(key)).intValue(); }
  JSONArray getJSONArray(String key) { return (JSONArray)values.get(key); }
 }
 static class JSONArray {
  final List<JSONObject> values = new ArrayList<>();
  int length() { return values.size(); }
  JSONArray put(JSONObject value) { values.add(value); return this; }
 }
 static class DisplayMetrics { int widthPixels=100, heightPixels=200; }
 static class Rect {
  int left,top,right,bottom;
  Rect() {} Rect(int l,int t,int r,int b) { left=l;top=t;right=r;bottom=b; }
  int centerX() { return (left+right)/2; } int centerY() { return (top+bottom)/2; }
  boolean isEmpty() { return left>=right || top>=bottom; }
  boolean intersect(int l,int t,int r,int b) {
   if (left>=r || right<=l || top>=b || bottom<=t) return false;
   left=Math.max(left,l);top=Math.max(top,t);right=Math.min(right,r);bottom=Math.min(bottom,b);return true;
  }
 }
 static class Bundle {
  final Map<String,Object> values=new HashMap<>();
  void putCharSequence(String key,CharSequence value) { values.put(key,value); }
  void putInt(String key,int value) { values.put(key,value); }
 }
 static class AccessibilityNodeInfo {
  static final int FOCUS_INPUT=1,ACTION_SET_TEXT=2,ACTION_SET_SELECTION=3;
  static final String ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE="text",ACTION_ARGUMENT_SELECTION_START_INT="start",ACTION_ARGUMENT_SELECTION_END_INT="end";
  String text="button"; int start,end,recycled,edits; boolean password,visible=true,clickable=true,editable=true,selectionAllowed=true;
  Rect bounds=new Rect(10,10,40,40); List<AccessibilityNodeInfo> children=new ArrayList<>();
  boolean isPassword() { return password; } String getText() { return text; } String getContentDescription() { return null; }
  boolean isVisibleToUser() { return visible; } boolean isClickable() { return clickable; } boolean isEditable() { return editable; }
  void getBoundsInScreen(Rect r) { r.left=bounds.left;r.top=bounds.top;r.right=bounds.right;r.bottom=bounds.bottom; }
  int getChildCount() { return children.size(); } AccessibilityNodeInfo getChild(int index) { return children.get(index); }
  int getTextSelectionStart() { return start; } int getTextSelectionEnd() { return end; }
  void recycle() { recycled++; }
  boolean performAction(int action, Bundle args) {
   if (action==ACTION_SET_TEXT) { text=args.values.get("text").toString();start=end=text.length();edits++;return true; }
   if (action==ACTION_SET_SELECTION && selectionAllowed) { start=(Integer)args.values.get("start");end=(Integer)args.values.get("end");return true; }
   return false;
  }
 }
 static class Build { static class VERSION { static int SDK_INT=30; } }
 static class SystemClock { static long elapsedRealtime() { return 10000; } }
 static class Display { static int DEFAULT_DISPLAY=0; }
 static class Base64 {
  static int NO_WRAP=0;
  static String encodeToString(byte[] value,int flags) { return java.util.Base64.getEncoder().encodeToString(value); }
 }
 static class HardwareBuffer implements AutoCloseable {
  int closes,created,recycled; String copiedOn=""; boolean copyFails;
  public void close() { require(++closes==1,"buffer closed twice"); }
 }
 static class Bitmap {
  static class Config { static final Config ARGB_8888=new Config(); }
  static class CompressFormat { static final CompressFormat JPEG=new CompressFormat(),PNG=new CompressFormat(); }
  final HardwareBuffer buffer; final int width,height;
  Bitmap(HardwareBuffer b,int w,int h) { buffer=b;width=w;height=h;b.created++; }
  static Bitmap wrapHardwareBuffer(HardwareBuffer b,Object color) { return new Bitmap(b,100,200); }
  Bitmap copy(Config config,boolean mutable) { buffer.copiedOn=Thread.currentThread().getName();return buffer.copyFails?null:new Bitmap(buffer,width,height); }
  static Bitmap createScaledBitmap(Bitmap b,int w,int h,boolean filter) { return new Bitmap(b.buffer,w,h); }
  int getWidth() { return width; } int getHeight() { return height; }
  boolean compress(CompressFormat format,int quality,ByteArrayOutputStream output) { output.write(1);return true; }
  void recycle() { buffer.recycled++; }
 }
 static class ScreenshotResult {
  final HardwareBuffer buffer; ScreenshotResult(HardwareBuffer b) { buffer=b; }
  HardwareBuffer getHardwareBuffer() { return buffer; } Object getColorSpace() { return null; }
 }
 interface TakeScreenshotCallback { void onSuccess(ScreenshotResult result); void onFailure(int error); }
 static class MainThread {
  final ExecutorService executor=Executors.newSingleThreadExecutor(r -> new Thread(r,"android-main"));
  void post(Runnable work) { executor.execute(work); }
 }
 final MainThread main=new MainThread(); long lastScreenshot;
 boolean uiFails,invalidateUi,delayed,valid=true; final CountDownLatch requested=new CountDownLatch(1);
 HardwareBuffer buffer=new HardwareBuffer(); Runnable deliver;
 AccessibilityNodeInfo focused=new AccessibilityNodeInfo();
 Executor getMainExecutor() { return main::post; }
 void takeScreenshot(int display,Executor executor,TakeScreenshotCallback callback) {
  deliver=() -> executor.execute(() -> callback.onSuccess(new ScreenshotResult(buffer)));
  requested.countDown(); if (!delayed) deliver.run();
 }
 JSONObject uiState() { if (invalidateUi) valid=false;if (uiFails) throw new IllegalStateException("UI unavailable");return new JSONObject().put("width",100).put("height",200).put("nodes",new JSONArray()); }
 AccessibilityNodeInfo findFocus(int kind) { return focused; }
 CommandGate gate() { return new CommandGate(() -> valid,SystemClock::elapsedRealtime,15000); }
 void close() throws Exception { main.executor.shutdown();require(main.executor.awaitTermination(2,TimeUnit.SECONDS),"main thread did not stop"); }
 /* PRODUCTION_METHODS */
 void backspace() throws Exception { /* PRODUCTION_BACKSPACE */ }
 static void screenshot() throws Exception {
  ControlBoundaryRepro h=new ControlBoundaryRepro();
  try {
   JSONObject result=h.observe(50,"jpeg",h.gate());
   require(result.getInt("width")==100 && result.values.containsKey("image_base64"),"image missing");
   require(!h.buffer.copiedOn.equals("android-main"),"pixel copy runs on main thread");
   require(h.buffer.closes==1 && h.buffer.created==h.buffer.recycled,"screenshot resources leaked");
  } finally { h.close(); }
 }
 static void optionalUi() throws Exception {
  ControlBoundaryRepro h=new ControlBoundaryRepro();h.uiFails=true;
  try { require(h.observe(50,"png",h.gate()).values.containsKey("image_base64"),"optional UI lost image"); }
  finally { h.close();require(h.buffer.closes==1 && h.buffer.created==h.buffer.recycled,"failed UI resources leaked"); }
 }
 static void lateCapture() throws Exception {
  ControlBoundaryRepro h=new ControlBoundaryRepro();h.delayed=true;
  java.util.concurrent.atomic.AtomicReference<Throwable> failure=new java.util.concurrent.atomic.AtomicReference<>();
  Thread command=new Thread(() -> { try { h.observe(50,"png",h.gate()); } catch(Throwable t) { failure.set(t); } },"command");
  try {
   command.start();require(h.requested.await(2,TimeUnit.SECONDS),"capture not requested");
   command.interrupt();command.join(2000);require(!command.isAlive() && failure.get()!=null,"cancellation did not finish");
   h.deliver.run();h.close();require(h.buffer.closes==1 && h.buffer.created==h.buffer.recycled,"late capture leaked");
  } finally { if (!h.main.executor.isShutdown()) h.close(); }
 }
 static void failedCopy() throws Exception {
  ControlBoundaryRepro h=new ControlBoundaryRepro();h.buffer.copyFails=true;
  try {
   try { h.observe(50,"png",h.gate());throw new AssertionError("null bitmap accepted"); } catch(Exception expected) {}
   require(h.buffer.closes==1 && h.buffer.created==h.buffer.recycled,"failed copy leaked");
  } finally { h.close(); }
 }
 static void cancelledUi() throws Exception {
  ControlBoundaryRepro h=new ControlBoundaryRepro();h.uiFails=true;h.invalidateUi=true;
  try {
   try { h.observe(50,"png",h.gate());throw new AssertionError("optional metadata bypassed command gate"); } catch(IllegalStateException expected) {}
   require(h.buffer.closes==1 && h.buffer.created==h.buffer.recycled,"cancelled UI resources leaked");
  } finally { h.close(); }
 }
 static void visibleBounds() throws Exception {
  ControlBoundaryRepro h=new ControlBoundaryRepro();
  try {
   AccessibilityNodeInfo clipped=new AccessibilityNodeInfo();clipped.bounds=new Rect(10,-100,40,20);
   AccessibilityNodeInfo outside=new AccessibilityNodeInfo();outside.bounds=new Rect(150,10,180,40);
   AccessibilityNodeInfo empty=new AccessibilityNodeInfo();empty.bounds=new Rect(20,10,20,40);
   clipped.children.add(outside);clipped.children.add(empty);
   JSONArray nodes=new JSONArray();h.collect(clipped,nodes,new DisplayMetrics(),0,new int[]{0});
   require(nodes.length()==1,"offscreen or empty bounds emitted");
   require(nodes.values.get(0).getInt("y")==50,"visible center must be y=10px, not the screen edge");
   require(outside.recycled==1 && empty.recycled==1,"child nodes not recycled");
   clipped.children.clear();
   for(int i=0;i<130;i++) { AccessibilityNodeInfo n=new AccessibilityNodeInfo();n.bounds=new Rect(150,10,180,40);clipped.children.add(n); }
   clipped.children.add(new AccessibilityNodeInfo());nodes=new JSONArray();
   h.collect(clipped,nodes,new DisplayMetrics(),0,new int[]{0});
   require(nodes.length()==2,"offscreen nodes exhausted the response budget before a visible button");
  } finally { h.close(); }
 }
 static void caret() throws Exception {
  ControlBoundaryRepro h=new ControlBoundaryRepro();
  try {
   h.focused.text="ab🙂cd";h.focused.start=h.focused.end=4;
   h.backspace();require(h.focused.text.equals("abcd") && h.focused.start==2 && h.focused.end==2,"backspace lost Unicode caret");
   h.backspace();require(h.focused.text.equals("acd") && h.focused.start==1,"repeated backspace deleted the wrong character");
   for(int[] selection:new int[][]{{2,4},{4,2}}) {
    h.focused.text="abcdef";h.focused.start=selection[0];h.focused.end=selection[1];h.backspace();
    require(h.focused.text.equals("abef") && h.focused.start==2 && h.focused.end==2,"selection direction changed deletion or caret");
   }
   h.focused.selectionAllowed=false;
   try { h.backspace();throw new AssertionError("failed selection restoration reported success"); } catch(IllegalStateException expected) {}
   h.focused.start=h.focused.end=0;int edits=h.focused.edits;h.backspace();
   require(h.focused.edits==edits,"backspace at start must not rewrite text");
   for(int[] selection:new int[][]{{-1,2},{2,-1},{h.focused.text.length()+1,0},{0,h.focused.text.length()+1}}) {
    h.focused.start=selection[0];h.focused.end=selection[1];
    try { h.backspace();throw new AssertionError("invalid selection accepted"); } catch(IllegalStateException expected) {}
    require(h.focused.edits==edits,"invalid selection edited text");
   }
   h.focused.start=h.focused.end=1;h.focused.password=true;
   try { h.backspace();throw new AssertionError("password text read"); } catch(IllegalStateException expected) {}
  } finally { h.close(); }
 }
 interface Check { void run() throws Exception; }
 public static void main(String[] args) throws Exception {
  String[] names={"worker pixel copy","optional UI metadata","late callback cleanup","failed copy cleanup","optional UI cancellation gate","visible node bounds","backspace caret"};
  Check[] checks={ControlBoundaryRepro::screenshot,ControlBoundaryRepro::optionalUi,ControlBoundaryRepro::lateCapture,ControlBoundaryRepro::failedCopy,ControlBoundaryRepro::cancelledUi,ControlBoundaryRepro::visibleBounds,ControlBoundaryRepro::caret};
  int failed=0;
  for(int i=0;i<checks.length;i++) { try { checks[i].run();System.out.println("PASS: "+names[i]); } catch(Throwable error) { failed++;System.out.println("FAIL: "+names[i]+" ("+error+")"); } }
  if(failed>0) throw new AssertionError(failed+" control regressions failed");
 }
}
'''
    methods = "\n".join(source_block(source, signature) for signature in (
        "private <T> T onMain(", "public JSONObject observe(", "private void collect("))
    code = code.replace("/* PRODUCTION_METHODS */", methods).replace(
        "/* PRODUCTION_BACKSPACE */", source_block(source, 'else if (key.equals("backspace"))', body=True))
    with tempfile.TemporaryDirectory(prefix="kira-control-") as directory:
        path = Path(directory) / "ControlBoundaryRepro.java"
        path.write_text(code, encoding="utf-8")
        subprocess.run([tool("javac"), "-encoding", "UTF-8", "-d", directory,
                        str(SOURCE / "CommandGate.java"), str(path)], check=True, timeout=30)
        subprocess.run([tool("java"), "-cp", directory, "top.kira.phone.ControlBoundaryRepro"], check=True, timeout=30)


if __name__ == "__main__":
    main()

package top.kira.phone;
import java.util.*;
import java.util.concurrent.Callable;
public class AppCatalogTest {
 public static void main(String[] args) throws Exception {
  long[] clock={0}; int[] scans={0};
  AppCatalog catalog=new AppCatalog(()->clock[0]);
  Callable<Map<String,String>> loader=()->{scans[0]++;return new HashMap<>(Map.of("b.pkg","B","a.pkg","A"));};
  SortedMap<String,String> first=catalog.snapshot(false,loader);
  if(!first.firstKey().equals("a.pkg"))throw new AssertionError();
  for(int page=0;page<20;page++) if(catalog.snapshot(false,loader)!=first)throw new AssertionError();
  if(scans[0]!=1)throw new AssertionError("Repeated pages must share one scan");
  clock[0]=14999;catalog.snapshot(false,loader);if(scans[0]!=1)throw new AssertionError();
  clock[0]=15000;catalog.snapshot(false,loader);if(scans[0]!=2)throw new AssertionError();
  catalog.snapshot(true,loader);if(scans[0]!=3)throw new AssertionError();
  try{first.put("x.pkg","X");throw new AssertionError();}catch(UnsupportedOperationException expected){}
  clock[0]=30000;
  try{catalog.snapshot(false,()->{throw new Exception("scan failed");});throw new AssertionError();}catch(Exception expected){}
  catalog.snapshot(false,loader);if(scans[0]!=4)throw new AssertionError("Failed scan must not refresh TTL");
  System.out.println("AppCatalog: cache, expiry, refresh, immutability and failure checks passed; 20 repeated reads use 1 scan");
 }
}

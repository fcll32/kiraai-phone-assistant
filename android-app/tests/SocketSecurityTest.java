package top.kira.phone;
import java.io.*;
import java.net.*;
import java.nio.file.*;
import java.security.*;
import javax.net.ssl.*;

/** Real TLS server/client checks; fixture PKCS12 files contain throwaway keys only. */
public class SocketSecurityTest {
 static void check(Path dir,String fixture,String host,String fingerprint,boolean expected) throws Exception {
  KeyStore keys=KeyStore.getInstance("PKCS12");
  try(InputStream input=Files.newInputStream(dir.resolve(fixture+".p12"))){keys.load(input,"test-only".toCharArray());}
  KeyManagerFactory km=KeyManagerFactory.getInstance(KeyManagerFactory.getDefaultAlgorithm());
  km.init(keys,"test-only".toCharArray());
  SSLContext context=SSLContext.getInstance("TLS");context.init(km.getKeyManagers(),null,null);
  try(SSLServerSocket server=(SSLServerSocket)context.getServerSocketFactory().createServerSocket(0,1,InetAddress.getByName("127.0.0.1"))) {
   server.setSoTimeout(3000);
   Thread peer=new Thread(()->{try(SSLSocket socket=(SSLSocket)server.accept()){socket.setSoTimeout(3000);socket.startHandshake();}catch(Exception ignored){}});
   peer.start();boolean succeeded=false;
   try(Socket raw=new Socket("127.0.0.1",server.getLocalPort());
       SSLSocket socket=(SSLSocket)SocketSecurity.factory(fingerprint).createSocket(raw,host,server.getLocalPort(),true)) {
    socket.setSoTimeout(3000);SSLParameters parameters=socket.getSSLParameters();
    parameters.setEndpointIdentificationAlgorithm("HTTPS");socket.setSSLParameters(parameters);
    socket.startHandshake();succeeded=true;
   }catch(SSLException expectedFailure){}
   peer.join(4000);if(peer.isAlive())throw new AssertionError("Server thread leaked");
   if(succeeded!=expected)throw new AssertionError(fixture+" / "+host+" unexpected TLS result");
  }
 }
 public static void main(String[] args) throws Exception {
  Path dir=Path.of(args[0]);
  String valid=Files.readString(dir.resolve("valid.sha256")).trim();
  check(dir,"valid","127.0.0.1",valid,true);
  check(dir,"valid","127.0.0.1","0".repeat(64),false);
  check(dir,"valid","localhost",valid,false);
  check(dir,"expired","127.0.0.1",Files.readString(dir.resolve("expired.sha256")).trim(),false);
  System.out.println("SocketSecurity: real TLS accepts valid pin and rejects wrong pin, host and expired cert");
 }
}

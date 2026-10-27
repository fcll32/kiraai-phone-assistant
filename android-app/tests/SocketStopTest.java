import java.net.*;
import java.util.concurrent.*;
import javax.net.ssl.*;
import org.java_websocket.client.WebSocketClient;
import org.java_websocket.handshake.ServerHandshake;

import top.kira.phone.SocketSecurity;
public class SocketStopTest {
 public static void main(String[] args) throws Exception {
  try(ServerSocket server=new ServerSocket(0,1,InetAddress.getByName("127.0.0.1"))) {
   WebSocketClient client=new WebSocketClient(new URI("wss://127.0.0.1:"+server.getLocalPort()+"/"),new org.java_websocket.drafts.Draft_6455(),null,15000) {
    public void onOpen(ServerHandshake h){} public void onMessage(String s){}
    public void onClose(int c,String r,boolean remote){}
    public void onError(Exception e){}
   };
   client.setSocketFactory(SSLContext.getDefault().getSocketFactory());
   try {
    client.connect();server.setSoTimeout(3000);
    try(Socket accepted=server.accept()) {
     accepted.setSoTimeout(3000);
     if(accepted.getInputStream().read()<0)throw new AssertionError("No ClientHello");
     SocketSecurity.closeNow(client);
     long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(3);
     while(System.nanoTime()<deadline&&Thread.getAllStackTraces().keySet().stream().anyMatch(t->t.isAlive()&&t.getName().contains("WebSocketConnectReadThread"))) Thread.sleep(10);
     boolean open=!client.getSocket().isClosed();
     long threads=Thread.getAllStackTraces().keySet().stream().filter(t->t.isAlive()&&t.getName().contains("WebSocketConnectReadThread")).count();
     if(open||threads!=0)throw new AssertionError("TLS socket/thread survived stop");
     SocketSecurity.closeNow(client); // Repeat shutdown must be harmless.
     System.out.println("PASS: stopped TLS handshake releases raw socket and read thread");
    }
   } finally { if(client.getSocket()!=null)client.getSocket().close();client.closeConnection(1000,"cleanup"); }
  }
  SocketSecurity.closeNow(null);
 }
}

package app.horas.local;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.AtomicFile;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import org.json.JSONObject;
import org.json.JSONException;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.time.LocalDate;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final int SAVE_DOCUMENT=1, OPEN_BACKUP=2;
    private static final String HOME="file:///android_asset/index.html";
    private WebView web;
    private Store store;
    private final ExecutorService files=Executors.newSingleThreadExecutor();
    private byte[] pendingExport;
    private String pendingName;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        store=new Store(this);
        FrameLayout root=new FrameLayout(this); root.setBackgroundColor(Color.rgb(50,22,79));
        web=new WebView(this); web.setBackgroundColor(Color.rgb(247,244,251));
        root.addView(web,new FrameLayout.LayoutParams(-1,-1)); setContentView(root);
        root.setOnApplyWindowInsetsListener((view,insets)->{
            if(Build.VERSION.SDK_INT>=30) {
                android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout());
                int bottom=bars.bottom;
                if(insets.isVisible(WindowInsets.Type.ime())) bottom=Math.max(bottom,insets.getInsets(WindowInsets.Type.ime()).bottom);
                view.setPadding(bars.left,bars.top,bars.right,bottom);
            } else view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
            return insets;
        });
        root.requestApplyInsets();
        WebSettings settings=web.getSettings(); settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(false); settings.setAllowFileAccess(false); settings.setAllowContentAccess(false);
        settings.setAllowFileAccessFromFileURLs(false); settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setJavaScriptCanOpenWindowsAutomatically(false); settings.setSupportMultipleWindows(false);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
                return !request.getUrl().toString().startsWith(HOME);
            }
        });
        web.addJavascriptInterface(new Bridge(),"HorasNative");
        web.loadUrl(HOME);
    }

    public final class Bridge {
        @JavascriptInterface public synchronized String call(String request) {
            try {
                if(request.length()>10000) throw new IllegalArgumentException("La solicitud es demasiado grande.");
                JSONObject q=new JSONObject(request); Object result=JSONObject.NULL;
                switch(q.getString("action")) {
                    case "preferences": result=store.preferences().put("has_previous_backup",previousFile().exists()); break;
                    case "month": result=store.month(q.getString("month")); break;
                    case "history": result=store.history(q.getInt("year")); break;
                    case "entry": result=store.entry(q.getString("day")); break;
                    case "quick": result=store.quick(q.getString("day"),q.getInt("minutes")); break;
                    case "save": store.save(q.getString("day"),q.getInt("minutes"),q.optString("note",""),q.optLong("revision",0)); break;
                    case "delete": store.delete(q.getString("day"),q.getLong("revision")); break;
                    case "preferences_save": store.setPreferences(q.getInt("minutes"),q.getString("rate")); break;
                    case "rate": store.setRate(q.getString("month"),q.getString("rate")); break;
                    case "paid": store.setPaid(q.getString("month"),q.getInt("paid"),q.getInt("minutes"),q.getInt("rate_cents")); break;
                    case "export":
                        String kind=q.getString("kind");
                        if("csv".equals(kind)) {
                            String month=Domain.month(q.getString("month"));
                            export(store.csv(month),"text/csv","horas-"+month+".csv");
                        } else if("backup".equals(kind)) {
                            export(store.backup().toString(2),"application/json","horas-copia-"+LocalDate.now()+".json");
                        } else if("previous".equals(kind)) {
                            export(new String(new AtomicFile(previousFile()).readFully(),StandardCharsets.UTF_8),"application/json","horas-antes-de-restaurar.json");
                        } else throw new IllegalArgumentException("El formato no es válido.");
                        break;
                    case "import": runOnUiThread(()->openBackup()); break;
                    default: throw new IllegalArgumentException("La acción no existe.");
                }
                return new JSONObject().put("ok",true).put("data",result==null?JSONObject.NULL:result).toString();
            } catch(Exception error) {
                try { return new JSONObject().put("ok",false).put("error",friendly(error)).toString(); }
                catch(JSONException impossible) { return "{\"ok\":false,\"error\":\"No se pudo completar la acción.\"}"; }
            }
        }
    }
    private String friendly(Exception error) {
        if(error instanceof IllegalArgumentException) return error.getMessage();
        if(error instanceof JSONException) return "El archivo o los datos no tienen un formato válido para Horas.";
        return "No se pudo guardar o leer el archivo. Comprueba que haya espacio disponible e inténtalo de nuevo.";
    }
    private File previousFile(){ return new File(getFilesDir(),"before-restore.json"); }
    private void notifyWeb(String message,boolean refresh) {
        runOnUiThread(()->{
            if(web!=null) web.evaluateJavascript("window.nativeFinished&&window.nativeFinished("+JSONObject.quote(message)+","+refresh+")",null);
        });
    }
    private void export(String content,String mime,String name) {
        byte[] bytes=content.getBytes(StandardCharsets.UTF_8);
        runOnUiThread(()->{
            pendingExport=bytes; pendingName=name;
            Intent intent=new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType(mime).putExtra(Intent.EXTRA_TITLE,name);
            try { startActivityForResult(intent,SAVE_DOCUMENT); }
            catch(ActivityNotFoundException error){ pendingExport=null; notifyWeb("No hay un selector de archivos disponible en este dispositivo.",false); }
        });
    }
    private void openBackup() {
        Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
        try { startActivityForResult(intent,OPEN_BACKUP); }
        catch(ActivityNotFoundException error){ notifyWeb("No hay un selector de archivos disponible en este dispositivo.",false); }
    }
    @Override protected void onActivityResult(int code,int result,Intent data) {
        super.onActivityResult(code,result,data);
        if(result!=RESULT_OK || data==null || data.getData()==null) { if(code==SAVE_DOCUMENT) pendingExport=null; return; }
        Uri uri=data.getData();
        if(code==SAVE_DOCUMENT) {
            final byte[] bytes=pendingExport; final String name=pendingName; pendingExport=null;
            if(bytes==null) { notifyWeb("Vuelve a pulsar en Exportar para guardar el archivo.",false); return; }
            files.execute(()->{
                try(OutputStream out=getContentResolver().openOutputStream(uri,"wt")) {
                    if(out==null) throw new IllegalArgumentException("No se puede escribir en el destino seleccionado.");
                    out.write(bytes); notifyWeb("Archivo guardado: "+name,false);
                } catch(Exception error){ notifyWeb(friendly(error),false); }
            });
        } else if(code==OPEN_BACKUP) files.execute(()->readBackup(uri));
    }
    private void readBackup(Uri uri) {
        try(InputStream in=getContentResolver().openInputStream(uri)) {
            if(in==null) throw new IllegalArgumentException("No se puede abrir la copia.");
            ByteArrayOutputStream bytes=new ByteArrayOutputStream(); byte[] buffer=new byte[8192]; int count;
            while((count=in.read(buffer))!=-1) {
                if(bytes.size()+count>2*1024*1024) throw new IllegalArgumentException("La copia supera el límite de 2 MB.");
                bytes.write(buffer,0,count);
            }
            JSONObject backup=new JSONObject(new String(bytes.toByteArray(),StandardCharsets.UTF_8)); Store.validateBackup(backup);
            runOnUiThread(()->new AlertDialog.Builder(this).setTitle("Restaurar copia")
                .setMessage("Se sustituirán todos los registros, tarifas y preferencias de este dispositivo. Se conservará una copia de los datos actuales antes de restaurar.")
                .setNegativeButton("Cancelar",null).setPositiveButton("Restaurar",(dialog,which)->files.execute(()->restoreBackup(backup))).show());
        } catch(Exception error) { notifyWeb(friendly(error),false); }
    }
    private void restoreBackup(JSONObject backup) {
        AtomicFile safety=new AtomicFile(previousFile()); FileOutputStream stream=null;
        try {
            byte[] old=store.backup().toString(2).getBytes(StandardCharsets.UTF_8);
            stream=safety.startWrite(); stream.write(old); safety.finishWrite(stream); stream=null;
            store.restore(backup); notifyWeb("Copia restaurada. Tus datos anteriores siguen disponibles en Ajustes.",true);
        } catch(Exception error) {
            if(stream!=null) safety.failWrite(stream);
            notifyWeb(friendly(error),false);
        }
    }
    @Override public void onBackPressed() {
        web.evaluateJavascript("window.goBack?window.goBack():false",result->{ if(!"true".equals(result)) MainActivity.super.onBackPressed(); });
    }
    WebView webForTests(){ return web; }
    @Override protected void onDestroy() {
        if(web!=null) { web.removeJavascriptInterface("HorasNative"); web.destroy(); web=null; }
        files.execute(()->store.close()); files.shutdown();
        super.onDestroy();
    }
}

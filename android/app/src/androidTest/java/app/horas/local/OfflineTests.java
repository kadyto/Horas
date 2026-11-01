package app.horas.local;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import org.json.JSONObject;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Runs against real Android SQLite and WebView, without a test-framework dependency. */
public final class OfflineTests extends Instrumentation {
    private int assertions=0;
    @Override public void onCreate(Bundle args){super.onCreate(args);start();}
    private void check(boolean condition,String message){assertions++;if(!condition)throw new AssertionError(message);}
    @Override public void onStart() {
        Bundle result=new Bundle(); Store store=null;
        try {
            Context context=getTargetContext(); context.deleteDatabase("offline-tests.sqlite3");
            store=new Store(context,"offline-tests.sqlite3");
            check(store.preferences().getInt("default_minutes")==120,"Default 2 h");
            store.setPreferences(90,"12,75");
            check(store.quick("2026-10-05",90),"First quick entry");
            check(!store.quick("2026-10-05",120),"No duplicate entry");
            check(store.month("2026-10").getLong("total")==1913,"Half-cent rounding");
            store.setPreferences(120,"20"); store.quick("2026-11-01",120);
            check(store.month("2026-10").getInt("rate_cents")==1275,"Historical rate");
            check(store.month("2026-11").getLong("total")==4000,"New month rate");
            store.setPaid("2026-10",1,90,1275);
            long rev=store.entry("2026-10-05").getLong("revision");
            store.save("2026-10-05",90,"Nota local",rev);
            check(store.month("2026-10").getInt("paid")==1,"Note keeps paid status");
            try{store.save("2026-10-05",120,"Obsoleta",rev);throw new AssertionError("Stale edit accepted");}catch(IllegalArgumentException expected){assertions++;}
            rev=store.entry("2026-10-05").getLong("revision");
            store.save("2026-10-05",120,"=FORMULA\nprueba",rev);
            check(store.month("2026-10").getInt("paid")==0,"Hours reset paid status");
            check(store.csv("2026-10").contains("'=FORMULA"),"CSV formula escaping");
            JSONObject backup=store.backup();
            JSONObject bad=new JSONObject(backup.toString());bad.getJSONArray("entries").put(bad.getJSONArray("entries").getJSONObject(0));
            try{store.restore(bad);throw new AssertionError("Bad backup accepted");}catch(IllegalArgumentException expected){assertions++;}
            check(store.backup().toString().equals(backup.toString()),"Invalid restore atomicity");
            store.quick("2026-10-07",60);store.restore(backup);
            check(store.entry("2026-10-07")==null,"Backup restoration");
            store.close();store=new Store(context,"offline-tests.sqlite3");
            check(store.entry("2026-10-05").getInt("minutes")==120,"SQLite survives reopen");
            check(context.checkSelfPermission("android.permission.INTERNET")==PackageManager.PERMISSION_DENIED,"No Internet permission");
            MainActivity activity=(MainActivity)startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            long deadline=System.currentTimeMillis()+30000;
            while(System.currentTimeMillis()<deadline && !"true".equals(js(activity,"!!document.querySelector('.calendar-grid')"))) Thread.sleep(250);
            check("true".equals(js(activity,"!!document.querySelector('.calendar-grid')")),"Offline WebView loads assets and SQLite");
            check("true".equals(js(activity,"document.querySelector('h1').textContent==='Cálculo de horas mensuales'")),"App opens without login");
            check("true".equals(js(activity,"document.documentElement.scrollWidth<=window.innerWidth")),"Mobile layout fits");
            Store appStore=new Store(context);JSONObject original=appStore.backup();
            try {
                js(activity,"document.querySelector('.empty-day').click();true");
                check("true".equals(js(activity,"document.querySelectorAll('.recorded').length===1")),"Calendar touch stores 2 h");
                check("true".equals(js(activity,"document.querySelector('.stats .stat strong').textContent.trim()==='2 h'")),"Default hours displayed");
                js(activity,"document.querySelector('.recorded a').click();true");Thread.sleep(250);
                js(activity,"document.querySelector('[data-hours=\"1.5\"]').click();document.querySelector('#entry-note').value='Nota de prueba';document.querySelector('#entry-form [type=submit]').click();true");Thread.sleep(250);
                check("true".equals(js(activity,"document.querySelector('.day-hours').textContent.trim()==='1,5 h'")),"Half-hour edit through native bridge");
                js(activity,"document.querySelector('#month-rate-input').value='12,75';document.querySelector('#rate-form [type=submit]').click();true");
                check("true".equals(js(activity,"document.querySelector('.total-stat strong').textContent==='19,13 €'")),"Monthly earnings through WebView");
                js(activity,"document.querySelector('[data-action=\"paid\"]').click();true");
                check("true".equals(js(activity,"document.querySelector('.balance-panel>.badge').textContent==='✓ Cobrado'")),"Payment toggle through UI");
                js(activity,"document.querySelector('.empty-day').click();true");
                check("true".equals(js(activity,"document.querySelector('.total-stat strong').textContent==='44,63 €'")),"Monthly rounding across days");
                check("true".equals(js(activity,"document.querySelector('.balance-panel>.badge').textContent==='◷ Pendiente'")),"New hours reset payment in UI");
            } finally {appStore.restore(original);appStore.close();}
            js(activity,"document.querySelector('[href=\"#/settings\"]').click();true");Thread.sleep(500);
            check("true".equals(js(activity,"!!document.querySelector('#prefs-form')")),"Settings navigation");
            runOnMainSync(activity::finish);
            result.putString("horasTests","ok");result.putInt("assertions",assertions);finish(Activity.RESULT_OK,result);
        }catch(Throwable error){result.putString("horasTests","failed");result.putString("failure",android.util.Log.getStackTraceString(error));finish(Activity.RESULT_CANCELED,result);}
        finally {if(store!=null)store.close();getTargetContext().deleteDatabase("offline-tests.sqlite3");}
    }
    private String js(MainActivity activity,String script)throws Exception {
        CountDownLatch latch=new CountDownLatch(1);AtomicReference<String> result=new AtomicReference<>();
        runOnMainSync(()->activity.webForTests().evaluateJavascript(script,value->{result.set(value);latch.countDown();}));
        if(!latch.await(10,TimeUnit.SECONDS))throw new AssertionError("WebView did not respond");
        return result.get();
    }
}

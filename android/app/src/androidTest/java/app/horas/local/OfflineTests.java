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
            checkWeeklyAndMigration(context,store);
            checkQuarterHoursAndMigration(context,store);
            check(context.checkSelfPermission("android.permission.INTERNET")==PackageManager.PERMISSION_DENIED,"No Internet permission");
            MainActivity activity=(MainActivity)startActivitySync(new Intent(context,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            long deadline=System.currentTimeMillis()+30000;
            while(System.currentTimeMillis()<deadline && !"true".equals(js(activity,"!!document.querySelector('.calendar-grid')"))) Thread.sleep(250);
            check("true".equals(js(activity,"!!document.querySelector('.calendar-grid')")),"Offline WebView loads assets and SQLite");
            check("true".equals(js(activity,"document.querySelector('h1').textContent==='Cálculo de horas mensuales'")),"App opens without login");
            check("true".equals(js(activity,"document.documentElement.scrollWidth<=window.innerWidth")),"Mobile layout fits");
            js(activity,"window.horasTestMonth=lastCalendarMonth;true");
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
                check("true".equals(js(activity,"document.querySelector('.balance-panel>.badge').textContent==='◐ Parcial'")),"New hours preserve earlier paid days");
                js(activity,"document.querySelector('#payment-frequency').value='weekly';document.querySelector('#payment-frequency').dispatchEvent(new Event('change',{bubbles:true}));true");
                check("true".equals(js(activity,"document.querySelector('h1').textContent==='Cálculo de horas semanales'")),"Weekly choice through UI");
                check("true".equals(js(activity,"!!document.querySelector('.selected-week')&&document.querySelectorAll('.week-select').length>=4")),"Selectable full weeks");
                check("true".equals(js(activity,"document.documentElement.scrollWidth<=window.innerWidth")),"Weekly layout fits");
                js(activity,"location.hash='/calendar?month=2026-11&week=2026-10-26';true");Thread.sleep(250);
                check("true".equals(js(activity,"document.querySelector('.week-navigation').textContent.indexOf('26/10/2026')>=0&&document.querySelector('.week-navigation').textContent.indexOf('01/11/2026')>=0")),"Cross-month week shown complete");
                js(activity,"document.querySelector('#payment-frequency').value='monthly';document.querySelector('#payment-frequency').dispatchEvent(new Event('change',{bubbles:true}));true");
                check("true".equals(js(activity,"document.querySelector('h1').textContent==='Cálculo de horas mensuales'")),"Switch back without deleting data");
                js(activity,"location.hash='/calendar?month='+window.horasTestMonth;true");Thread.sleep(250);
                js(activity,"document.querySelector('.recorded a').click();true");Thread.sleep(250);
                js(activity,"document.querySelector('[data-step=\"0.25\"]').click();true");
                check("true".equals(js(activity,"document.querySelector('#entry-hours').value==='1.75'")),"Plus button adds 15 minutes");
                js(activity,"document.querySelector('[data-step=\"-0.25\"]').click();document.querySelector('[data-step=\"-0.25\"]').click();true");
                check("true".equals(js(activity,"document.querySelector('#entry-hours').value==='1.25'")),"Minus button subtracts 15 minutes");
                js(activity,"document.querySelector('[data-hours=\"0.25\"]').click();document.querySelector('[data-step=\"-0.25\"]').click();true");
                check("true".equals(js(activity,"document.querySelector('#entry-hours').value==='0.25'")),"Minimum is exactly 15 minutes");
                js(activity,"document.querySelector('#entry-form [type=submit]').click();true");Thread.sleep(250);
                check("true".equals(js(activity,"document.querySelector('.day-hours').textContent.trim()==='0,25 h'")),"Quarter hour saved through UI");
                check("true".equals(js(activity,"document.querySelector('#quick-hours option[value=\"15\"]')!==null&&document.querySelector('#quick-hours option[value=\"45\"]')!==null")),"Quick selector has 15-minute slots");
            } finally {appStore.restore(original);appStore.close();}
            js(activity,"document.querySelector('[href=\"#/settings\"]').click();true");Thread.sleep(500);
            check("true".equals(js(activity,"!!document.querySelector('#prefs-form')")),"Settings navigation");
            runOnMainSync(activity::finish);
            result.putString("horasTests","ok");result.putInt("assertions",assertions);finish(Activity.RESULT_OK,result);
        }catch(Throwable error){result.putString("horasTests","failed");result.putString("failure",android.util.Log.getStackTraceString(error));finish(Activity.RESULT_CANCELED,result);}
        finally {if(store!=null)store.close();getTargetContext().deleteDatabase("offline-tests.sqlite3");}
    }
    private void checkQuarterHoursAndMigration(Context context,Store store)throws Exception {
        try(java.io.InputStream input=getContext().getAssets().open("quarter-hours-v2.json");java.io.ByteArrayOutputStream out=new java.io.ByteArrayOutputStream()){
            byte[] buffer=new byte[2048];int count;while((count=input.read(buffer))!=-1)out.write(buffer,0,count);
            store.restore(new JSONObject(new String(out.toByteArray(),java.nio.charset.StandardCharsets.UTF_8)));
        }
        JSONObject summary=store.period("weekly","2026-11-02");
        check(summary.getInt("minutes")==135&&summary.getLong("total")==2869,"Quarter hours total rounds correctly");
        check(summary.getLong("paid_total")==319&&summary.getLong("pending_total")==2550,"Quarter hours paid and pending balance");
        check(store.preferences().getInt("default_minutes")==15,"Quarter-hour default imported");
        JSONObject copy=store.backup();store.restore(copy);
        check(store.backup().toString().equals(copy.toString()),"Quarter-hour JSON roundtrip");
        check(store.csv("weekly","2026-11-02").contains("0,25")&&store.csv("weekly","2026-11-02").contains("0,75"),"Quarter hours in CSV");
        context.deleteDatabase("quarter-migration.sqlite3");
        try(android.database.sqlite.SQLiteDatabase db=context.openOrCreateDatabase("quarter-migration.sqlite3",0,null)){
            db.execSQL("CREATE TABLE settings(id INTEGER PRIMARY KEY,default_minutes INTEGER CHECK(default_minutes BETWEEN 30 AND 1440 AND default_minutes%30=0),default_rate_cents INTEGER,payment_frequency TEXT)");
            db.execSQL("INSERT INTO settings VALUES(1,90,2000,'weekly')");
            db.execSQL("CREATE TABLE months(month TEXT PRIMARY KEY,rate_cents INTEGER,paid INTEGER)");db.execSQL("INSERT INTO months VALUES('2026-11',1000,1)");
            db.execSQL("CREATE TABLE weeks(week TEXT PRIMARY KEY,rate_cents INTEGER)");db.execSQL("INSERT INTO weeks VALUES('2026-11-02',1800)");
            db.execSQL("CREATE TABLE entries(day TEXT PRIMARY KEY,month TEXT REFERENCES months(month),minutes INTEGER CHECK(minutes BETWEEN 30 AND 1440 AND minutes%30=0),note TEXT,revision INTEGER,rate_cents INTEGER,paid INTEGER)");
            db.execSQL("INSERT INTO entries VALUES('2026-11-02','2026-11',90,'Conservado',88,1275,1)");db.setVersion(2);
        }
        try(Store migrated=new Store(context,"quarter-migration.sqlite3")){
            JSONObject old=migrated.entry("2026-11-02");
            check(old.getInt("minutes")==90&&old.getInt("rate_cents")==1275&&old.getInt("paid")==1&&old.getLong("revision")==88,"V2 upgrade retains hours, price, payment and revision");
            check("weekly".equals(migrated.preferences().getString("payment_frequency")),"V2 upgrade retains payment mode");
            migrated.setPreferences(15,"20","weekly");migrated.quick("2026-11-03",15);
            check(migrated.entry("2026-11-03").getInt("minutes")==15&&migrated.entry("2026-11-03").getInt("rate_cents")==1800,"Migrated constraints accept 15 minutes with existing weekly price");
            try{migrated.getWritableDatabase().execSQL("UPDATE entries SET minutes=20");throw new AssertionError("Invalid slot accepted");}catch(android.database.sqlite.SQLiteConstraintException expected){assertions++;}
        }
        context.deleteDatabase("quarter-migration.sqlite3");
    }
    private void checkWeeklyAndMigration(Context context,Store store)throws Exception {
        byte[] bytes;
        try(java.io.InputStream input=getContext().getAssets().open("payments-v2.json");java.io.ByteArrayOutputStream out=new java.io.ByteArrayOutputStream()){
            byte[] buffer=new byte[2048];int count;while((count=input.read(buffer))!=-1)out.write(buffer,0,count);bytes=out.toByteArray();
        }
        store.restore(new JSONObject(new String(bytes,java.nio.charset.StandardCharsets.UTF_8)));
        JSONObject week=store.period("weekly","2026-10-26");
        check(week.getLong("total")==5500&&week.getLong("paid_total")==1500&&week.getLong("pending_total")==4000,"Shared JSON fixture amounts");
        check(week.getBoolean("mixed_rates")&&week.getBoolean("partial"),"Mixed prices and partial collection");
        store.setPaid("weekly","2026-10-26",1,210,2000,week.getString("signature"));
        check(store.month("2026-11").getBoolean("partial")&&store.month("2026-11").getLong("pending_total")==3000,"Weekly payment shared with monthly view");
        String original=store.backup().getJSONArray("entries").toString();store.setFrequency("monthly");store.setFrequency("weekly");
        check(original.equals(store.backup().getJSONArray("entries").toString()),"Switch cadence preserves entries, prices and payments");
        store.setRate("weekly","2026-10-26","15");
        check(store.period("weekly","2026-10-26").getLong("total")==5250,"Weekly price across months");
        check(store.period("weekly","2026-11-02").getLong("total")==3000,"Other week unaffected");
        check(store.csv("weekly","2026-10-26").contains("2026-10-31")&&!store.csv("weekly","2026-10-26").contains("2026-11-02"),"Weekly CSV limits");
        JSONObject saved=store.backup();store.restore(saved);check(store.backup().toString().equals(saved.toString()),"V2 JSON roundtrip");
        JSONObject legacy=new JSONObject("{\"format\":\"horas\",\"version\":1,\"settings\":{\"default_minutes\":120,\"default_rate_cents\":1000},\"months\":[{\"month\":\"2026-10\",\"rate_cents\":1275,\"paid\":1}],\"entries\":[{\"day\":\"2026-10-31\",\"minutes\":90,\"note\":\"Legacy\"}]}");
        store.restore(legacy);check(store.month("2026-10").getLong("total")==1913&&store.month("2026-10").getInt("paid")==1,"V1 JSON migration");
        context.deleteDatabase("migration-tests.sqlite3");
        try(android.database.sqlite.SQLiteDatabase db=context.openOrCreateDatabase("migration-tests.sqlite3",0,null)){
            db.execSQL("CREATE TABLE settings(id INTEGER PRIMARY KEY,default_minutes INTEGER,default_rate_cents INTEGER)");
            db.execSQL("INSERT INTO settings VALUES(1,120,1000)");db.execSQL("CREATE TABLE months(month TEXT PRIMARY KEY,rate_cents INTEGER,paid INTEGER)");
            db.execSQL("INSERT INTO months VALUES('2026-10',1275,1)");db.execSQL("CREATE TABLE entries(day TEXT PRIMARY KEY,month TEXT,minutes INTEGER,note TEXT,revision INTEGER)");
            db.execSQL("INSERT INTO entries VALUES('2026-10-31','2026-10',90,'Legacy',3)");db.setVersion(1);
        }
        try(Store migrated=new Store(context,"migration-tests.sqlite3")){
            check(migrated.month("2026-10").getLong("total")==1913&&migrated.month("2026-10").getInt("paid")==1,"SQLite in-place upgrade preserves rates and collection");
            check("monthly".equals(migrated.preferences().getString("payment_frequency")),"Migration defaults to monthly");
        }
        context.deleteDatabase("migration-tests.sqlite3");
    }
    private String js(MainActivity activity,String script)throws Exception {
        CountDownLatch latch=new CountDownLatch(1);AtomicReference<String> result=new AtomicReference<>();
        runOnMainSync(()->activity.webForTests().evaluateJavascript(script,value->{result.set(value);latch.countDown();}));
        if(!latch.await(10,TimeUnit.SECONDS))throw new AssertionError("WebView did not respond");
        return result.get();
    }
}

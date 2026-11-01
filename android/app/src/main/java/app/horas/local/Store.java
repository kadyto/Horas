package app.horas.local;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import java.security.SecureRandom;
import java.util.HashSet;
import java.util.Set;

/** Private on-device SQLite; no login tables, server, or network dependency. */
public final class Store extends SQLiteOpenHelper {
    private final SecureRandom random = new SecureRandom();
    public Store(Context context) { this(context, "horas.sqlite3"); }
    Store(Context context, String name) { super(context, name, null, 3); setWriteAheadLoggingEnabled(true); }

    @Override public void onConfigure(SQLiteDatabase db) { db.setForeignKeyConstraintsEnabled(true); }
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK(id=1),default_minutes INTEGER NOT NULL CHECK(default_minutes BETWEEN 15 AND 1440 AND default_minutes%15=0),default_rate_cents INTEGER NOT NULL CHECK(default_rate_cents BETWEEN 0 AND 1000000),payment_frequency TEXT NOT NULL DEFAULT 'monthly' CHECK(payment_frequency IN('monthly','weekly')))");
        db.execSQL("INSERT INTO settings VALUES(1,120,0,'monthly')");
        db.execSQL("CREATE TABLE months(month TEXT PRIMARY KEY,rate_cents INTEGER NOT NULL CHECK(rate_cents BETWEEN 0 AND 1000000),paid INTEGER NOT NULL DEFAULT 0 CHECK(paid IN(0,1)))");
        db.execSQL("CREATE TABLE entries(day TEXT PRIMARY KEY,month TEXT NOT NULL REFERENCES months(month),minutes INTEGER NOT NULL CHECK(minutes BETWEEN 15 AND 1440 AND minutes%15=0),note TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL,rate_cents INTEGER NOT NULL DEFAULT 0 CHECK(rate_cents BETWEEN 0 AND 1000000),paid INTEGER NOT NULL DEFAULT 0 CHECK(paid IN(0,1)))");
        db.execSQL("CREATE INDEX entries_month ON entries(month)");
        db.execSQL("CREATE TABLE weeks(week TEXT PRIMARY KEY,rate_cents INTEGER NOT NULL CHECK(rate_cents BETWEEN 0 AND 1000000))");
    }
    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        if(oldVersion<2) {
            db.execSQL("ALTER TABLE settings ADD COLUMN payment_frequency TEXT NOT NULL DEFAULT 'monthly' CHECK(payment_frequency IN('monthly','weekly'))");
            db.execSQL("ALTER TABLE entries ADD COLUMN rate_cents INTEGER NOT NULL DEFAULT 0 CHECK(rate_cents BETWEEN 0 AND 1000000)");
            db.execSQL("ALTER TABLE entries ADD COLUMN paid INTEGER NOT NULL DEFAULT 0 CHECK(paid IN(0,1))");
            db.execSQL("UPDATE entries SET rate_cents=(SELECT rate_cents FROM months WHERE month=entries.month),paid=(SELECT paid FROM months WHERE month=entries.month)");
            db.execSQL("CREATE TABLE weeks(week TEXT PRIMARY KEY,rate_cents INTEGER NOT NULL CHECK(rate_cents BETWEEN 0 AND 1000000))");
        }
        if(oldVersion<3) {
            db.execSQL("CREATE TABLE settings_quarter(id INTEGER PRIMARY KEY CHECK(id=1),default_minutes INTEGER NOT NULL CHECK(default_minutes BETWEEN 15 AND 1440 AND default_minutes%15=0),default_rate_cents INTEGER NOT NULL CHECK(default_rate_cents BETWEEN 0 AND 1000000),payment_frequency TEXT NOT NULL DEFAULT 'monthly' CHECK(payment_frequency IN('monthly','weekly')))");
            db.execSQL("INSERT INTO settings_quarter SELECT id,default_minutes,default_rate_cents,payment_frequency FROM settings");
            db.execSQL("DROP TABLE settings");db.execSQL("ALTER TABLE settings_quarter RENAME TO settings");
            db.execSQL("CREATE TABLE entries_quarter(day TEXT PRIMARY KEY,month TEXT NOT NULL REFERENCES months(month),minutes INTEGER NOT NULL CHECK(minutes BETWEEN 15 AND 1440 AND minutes%15=0),note TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL,rate_cents INTEGER NOT NULL DEFAULT 0 CHECK(rate_cents BETWEEN 0 AND 1000000),paid INTEGER NOT NULL DEFAULT 0 CHECK(paid IN(0,1)))");
            db.execSQL("INSERT INTO entries_quarter SELECT day,month,minutes,note,revision,rate_cents,paid FROM entries");
            db.execSQL("DROP TABLE entries");db.execSQL("ALTER TABLE entries_quarter RENAME TO entries");
            db.execSQL("CREATE INDEX entries_month ON entries(month)");
            try(Cursor cursor=db.rawQuery("PRAGMA foreign_key_check",null)){
                if(cursor.moveToFirst())throw new IllegalStateException("La base de datos contiene referencias no válidas; no se ha aplicado la migración.");
            }
        }
    }
    private long newRevision() { return random.nextLong() & 0xfffffffffffffL; }
    private JSONObject row(Cursor cursor) throws JSONException {
        JSONObject result = new JSONObject();
        for (int i = 0; i < cursor.getColumnCount(); i++) {
            result.put(cursor.getColumnName(i), cursor.getType(i) == Cursor.FIELD_TYPE_INTEGER ? cursor.getLong(i) : cursor.getString(i));
        }
        return result;
    }
    private JSONObject one(String sql, String... args) throws JSONException {
        try (Cursor c = getReadableDatabase().rawQuery(sql, args)) { return c.moveToFirst() ? row(c) : null; }
    }
    private JSONArray many(String sql, String... args) throws JSONException {
        JSONArray result = new JSONArray();
        try (Cursor c = getReadableDatabase().rawQuery(sql, args)) { while(c.moveToNext()) result.put(row(c)); }
        return result;
    }
    public synchronized JSONObject preferences() throws JSONException {
        return one("SELECT default_minutes,default_rate_cents,payment_frequency FROM settings WHERE id=1");
    }
    private void ensureMonth(String month) throws JSONException {
        getWritableDatabase().execSQL("INSERT OR IGNORE INTO months(month,rate_cents) VALUES(?,?)", new Object[]{month,preferences().getInt("default_rate_cents")});
    }
    public synchronized JSONObject entry(String day) throws JSONException {
        return one("SELECT * FROM entries WHERE day=?", Domain.day(day));
    }
    private String[] bounds(String frequency,String key) {
        Domain.frequency(frequency);
        if("weekly".equals(frequency)){Domain.week(key);return new String[]{key,java.time.LocalDate.parse(key).plusDays(6).toString()};}
        Domain.month(key);java.time.YearMonth month=java.time.YearMonth.parse(key);
        return new String[]{month.atDay(1).toString(),month.atEndOfMonth().toString()};
    }
    public synchronized JSONObject month(String month)throws JSONException{return period("monthly",month);}
    public synchronized JSONObject period(String frequency,String key)throws JSONException {
        String[] range=bounds(frequency,key); boolean weekly="weekly".equals(frequency);
        JSONObject pref=preferences(),saved=one("SELECT rate_cents FROM "+(weekly?"weeks WHERE week=?":"months WHERE month=?"),key);
        int defaultRate=saved==null?pref.getInt("default_rate_cents"):saved.getInt("rate_cents");
        JSONArray entries=many("SELECT * FROM entries WHERE day BETWEEN ? AND ? ORDER BY day",range);
        int minutes=0,paidDays=0;long numerator=0,paidNumerator=0;Set<Integer> rates=new HashSet<>();StringBuilder signature=new StringBuilder();
        for(int i=0;i<entries.length();i++) {
            JSONObject row=entries.getJSONObject(i);int m=row.getInt("minutes"),rate=row.getInt("rate_cents"),paid=row.getInt("paid");
            minutes+=m;numerator+=(long)m*rate;if(paid==1){paidDays++;paidNumerator+=(long)m*rate;}rates.add(rate);
            signature.append(row.getString("day")).append(':').append(m).append(':').append(rate).append(':').append(paid).append(':').append(row.getLong("revision")).append(';');
        }
        String digest;
        try {
            byte[] hash=java.security.MessageDigest.getInstance("SHA-256").digest(signature.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            StringBuilder hex=new StringBuilder();for(byte v:hash)hex.append(String.format(java.util.Locale.ROOT,"%02x",v&255));digest=hex.toString();
        } catch(java.security.NoSuchAlgorithmException impossible){throw new IllegalStateException(impossible);}
        long total=Domain.earnings(numerator,1),paidTotal=Domain.earnings(paidNumerator,1);
        if(saved==null&&rates.size()==1)defaultRate=rates.iterator().next();
        return new JSONObject().put("frequency",frequency).put("key",key).put("month",weekly?range[0].substring(0,7):key)
            .put("start",range[0]).put("end",range[1]).put("rate_cents",rates.size()==1?rates.iterator().next():defaultRate)
            .put("default_rate_cents",defaultRate).put("mixed_rates",rates.size()>1).put("entries",entries).put("minutes",minutes).put("days",entries.length())
            .put("paid_days",paidDays).put("paid",entries.length()>0&&paidDays==entries.length()?1:0).put("partial",paidDays>0&&paidDays<entries.length())
            .put("total",total).put("paid_total",paidTotal).put("pending_total",total-paidTotal).put("signature",digest).put("prefs",pref);
    }
    public synchronized JSONArray calendarEntries(String month)throws JSONException {
        Domain.month(month);java.time.YearMonth ym=java.time.YearMonth.parse(month);
        String start=Domain.weekStart(ym.atDay(1).toString()),end=java.time.LocalDate.parse(Domain.weekStart(ym.atEndOfMonth().toString())).plusDays(6).toString();
        return many("SELECT * FROM entries WHERE day BETWEEN ? AND ? ORDER BY day",start,end);
    }
    public synchronized JSONArray history(int year)throws JSONException{return history(year,preferences().getString("payment_frequency"));}
    public synchronized JSONArray history(int year,String frequency)throws JSONException {
        Domain.frequency(frequency);JSONArray result=new JSONArray();
        if("weekly".equals(frequency)){for(String key:Domain.yearWeeks(year))result.put(period(frequency,key));}
        else {
            if(year<2000||year>2100)throw new IllegalArgumentException("El año debe estar entre 2000 y 2100.");
            for(int m=1;m<=12;m++)result.put(month(String.format(java.util.Locale.ROOT,"%04d-%02d",year,m)));
        }
        return result;
    }
    private int entryRate(String day)throws JSONException {
        JSONObject pref=preferences();if("weekly".equals(pref.getString("payment_frequency"))){
            String key=Domain.weekStart(day);int rate=period("weekly",key).getInt("default_rate_cents");
            getWritableDatabase().execSQL("INSERT OR IGNORE INTO weeks VALUES(?,?)",new Object[]{key,rate});
            return one("SELECT rate_cents FROM weeks WHERE week=?",key).getInt("rate_cents");
        }
        ensureMonth(day.substring(0,7));return one("SELECT rate_cents FROM months WHERE month=?",day.substring(0,7)).getInt("rate_cents");
    }
    public synchronized boolean quick(String day, int minutes) throws JSONException {
        Domain.day(day); Domain.minutes(minutes);
        SQLiteDatabase db = getWritableDatabase(); db.beginTransaction();
        try {
            ensureMonth(day.substring(0,7));
            boolean created = entry(day) == null;
            if(created) {
                db.execSQL("INSERT INTO entries(day,month,minutes,note,revision,rate_cents,paid) VALUES(?,?,?,?,?,?,0)",new Object[]{day,day.substring(0,7),minutes,"",newRevision(),entryRate(day)});
            }
            db.setTransactionSuccessful(); return created;
        } finally { db.endTransaction(); }
    }
    public synchronized void save(String day,int minutes,String note,long revision) throws JSONException {
        Domain.day(day); Domain.minutes(minutes);
        note=note.trim();
        if(note.codePointCount(0,note.length())>500) throw new IllegalArgumentException("La nota puede tener como máximo 500 caracteres.");
        SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
            JSONObject old=entry(day);
            if((old==null?0:old.getLong("revision"))!=revision) throw new IllegalArgumentException("Este día ha cambiado. Vuelve al calendario y abre de nuevo el registro.");
            ensureMonth(day.substring(0,7));
            ContentValues values=new ContentValues(); values.put("day",day); values.put("month",day.substring(0,7));
            values.put("minutes",minutes); values.put("note",note); values.put("revision",newRevision());
            values.put("rate_cents",old==null?entryRate(day):old.getInt("rate_cents"));
            values.put("paid",old==null||old.getInt("minutes")!=minutes?0:old.getInt("paid"));
            if(old==null) db.insertOrThrow("entries",null,values); else db.update("entries",values,"day=?",new String[]{day});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    public synchronized void delete(String day,long revision) {
        Domain.day(day); SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
            if(db.delete("entries","day=? AND revision=?",new String[]{day,String.valueOf(revision)})!=1)
                throw new IllegalArgumentException("El registro ha cambiado o ya se ha eliminado.");
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    public synchronized void setPreferences(int minutes,String rate)throws JSONException {setPreferences(minutes,rate,preferences().getString("payment_frequency"));}
    public synchronized void setPreferences(int minutes,String rate,String frequency) {
        Domain.minutes(minutes);int cents=Domain.rate(rate);Domain.frequency(frequency);
        getWritableDatabase().execSQL("UPDATE settings SET default_minutes=?,default_rate_cents=?,payment_frequency=? WHERE id=1",new Object[]{minutes,cents,frequency});
    }
    public synchronized void setFrequency(String frequency){Domain.frequency(frequency);getWritableDatabase().execSQL("UPDATE settings SET payment_frequency=? WHERE id=1",new Object[]{frequency});}
    public synchronized void setRate(String month,String rate)throws JSONException {setRate("monthly",month,rate);}
    public synchronized void setRate(String frequency,String key,String rate)throws JSONException {
        String[] range=bounds(frequency,key);int cents=Domain.rate(rate);boolean weekly="weekly".equals(frequency);
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();
        try {
            if(weekly)db.execSQL("INSERT OR IGNORE INTO weeks VALUES(?,?)",new Object[]{key,cents});else ensureMonth(key);
            db.execSQL("UPDATE "+(weekly?"weeks":"months")+" SET rate_cents=? WHERE "+(weekly?"week":"month")+"=?",new Object[]{cents,key});
            db.execSQL("UPDATE entries SET paid=CASE WHEN rate_cents!=? THEN 0 ELSE paid END,rate_cents=?,revision=revision+1 WHERE day BETWEEN ? AND ?",new Object[]{cents,cents,range[0],range[1]});
            db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    public synchronized void setPaid(String month,int paid,int minutes,int rate)throws JSONException {setPaid("monthly",month,paid,minutes,rate,null);}
    public synchronized void setPaid(String frequency,String key,int paid,int expectedMinutes,int expectedRate,String signature)throws JSONException {
        if(paid!=0&&paid!=1)throw new IllegalArgumentException("El estado de cobro no es válido.");
        SQLiteDatabase db=getWritableDatabase();db.beginTransaction();
        try {
            JSONObject data=period(frequency,key);
            if(data.getInt("days")==0)throw new IllegalArgumentException("Añade horas antes de marcar el periodo como cobrado.");
            if((signature!=null&&!signature.equals(data.getString("signature")))||(signature==null&&(data.getInt("minutes")!=expectedMinutes||data.getInt("rate_cents")!=expectedRate)))
                throw new IllegalArgumentException("El total ha cambiado. Revisa el periodo antes de marcar el cobro.");
            db.execSQL("UPDATE entries SET paid=? WHERE day BETWEEN ? AND ?",new Object[]{paid,data.getString("start"),data.getString("end")});db.setTransactionSuccessful();
        }finally{db.endTransaction();}
    }
    public synchronized JSONObject backup() throws JSONException {
        SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
            JSONObject data=new JSONObject().put("format","horas").put("version",2).put("settings",preferences())
                .put("months",many("SELECT month,rate_cents,paid FROM months ORDER BY month"))
                .put("weeks",many("SELECT * FROM weeks ORDER BY week"))
                .put("entries",many("SELECT day,minutes,note,rate_cents,paid FROM entries ORDER BY day"));
            JSONArray months=data.getJSONArray("months");for(int i=0;i<months.length();i++){JSONObject row=months.getJSONObject(i);row.put("paid",month(row.getString("month")).getInt("paid"));}
            db.setTransactionSuccessful(); return data;
        } finally { db.endTransaction(); }
    }
    private static int strictInt(JSONObject row,String key,int low,int high,int step) throws JSONException {
        Object value=row.get(key);
        if(!(value instanceof Integer || value instanceof Long)) throw new IllegalArgumentException("La copia contiene una cantidad no válida.");
        long n=((Number)value).longValue();
        if(n<low || n>high || n%step!=0) throw new IllegalArgumentException("La copia contiene una cantidad no válida.");
        return (int)n;
    }
    public static void validateBackup(JSONObject data) throws JSONException {
        if(!"horas".equals(data.optString("format")) || strictInt(data,"version",1,2,1)<1)
            throw new IllegalArgumentException("La copia no tiene un formato compatible con Horas.");
        int version=data.getInt("version");
        JSONObject prefs=data.getJSONObject("settings");
        if(version==2)Domain.frequency(prefs.getString("payment_frequency"));
        strictInt(prefs,"default_minutes",15,1440,15); strictInt(prefs,"default_rate_cents",0,1000000,1);
        JSONArray months=data.getJSONArray("months"),entries=data.getJSONArray("entries");
        if(months.length()>1212 || entries.length()>37000) throw new IllegalArgumentException("La copia contiene demasiados registros.");
        Set<String> seenMonths=new HashSet<>(),seenDays=new HashSet<>();
        for(int i=0;i<months.length();i++) {
            JSONObject row=months.getJSONObject(i); String month=Domain.month(row.getString("month"));
            if(!seenMonths.add(month)) throw new IllegalArgumentException("La copia contiene meses duplicados.");
            strictInt(row,"rate_cents",0,1000000,1); strictInt(row,"paid",0,1,1);
        }
        if(version==2){
            JSONArray weeks=data.getJSONArray("weeks");if(weeks.length()>5400)throw new IllegalArgumentException("La copia contiene demasiadas semanas.");
            Set<String> seenWeeks=new HashSet<>();for(int i=0;i<weeks.length();i++){JSONObject row=weeks.getJSONObject(i);if(!seenWeeks.add(Domain.week(row.getString("week"))))throw new IllegalArgumentException("La copia contiene semanas duplicadas.");strictInt(row,"rate_cents",0,1000000,1);}
        }
        for(int i=0;i<entries.length();i++) {
            JSONObject row=entries.getJSONObject(i); String day=Domain.day(row.getString("day"));
            if(version==2){strictInt(row,"rate_cents",0,1000000,1);strictInt(row,"paid",0,1,1);}
            if(!seenDays.add(day) || !seenMonths.contains(day.substring(0,7))) throw new IllegalArgumentException("La copia contiene días duplicados o sin mes asociado.");
            strictInt(row,"minutes",15,1440,15);
            if(!(row.get("note") instanceof String)) throw new IllegalArgumentException("La copia contiene una nota no válida.");
            String note=row.getString("note");
            if(note.codePointCount(0,note.length())>500) throw new IllegalArgumentException("La copia contiene una nota demasiado larga.");
        }
    }
    public synchronized void restore(JSONObject data) throws JSONException {
        validateBackup(data); SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
            db.delete("entries",null,null); db.delete("months",null,null);db.delete("weeks",null,null);
            JSONObject prefs=data.getJSONObject("settings");
            setPreferences(prefs.getInt("default_minutes"),java.math.BigDecimal.valueOf(prefs.getInt("default_rate_cents"),2).toPlainString(),data.getInt("version")==2?prefs.getString("payment_frequency"):"monthly");
            JSONArray months=data.getJSONArray("months"),entries=data.getJSONArray("entries");
            for(int i=0;i<months.length();i++) {
                JSONObject row=months.getJSONObject(i);
                db.execSQL("INSERT INTO months VALUES(?,?,?)",new Object[]{row.getString("month"),row.getInt("rate_cents"),row.getInt("paid")});
            }
            for(int i=0;i<entries.length();i++) {
                JSONObject row=entries.getJSONObject(i); String day=row.getString("day");
                JSONObject legacy=one("SELECT rate_cents,paid FROM months WHERE month=?",day.substring(0,7));
                int rate=data.getInt("version")==2?row.getInt("rate_cents"):legacy.getInt("rate_cents"),paid=data.getInt("version")==2?row.getInt("paid"):legacy.getInt("paid");
                db.execSQL("INSERT INTO entries(day,month,minutes,note,revision,rate_cents,paid) VALUES(?,?,?,?,?,?,?)",new Object[]{day,day.substring(0,7),row.getInt("minutes"),row.getString("note"),newRevision(),rate,paid});
            }
            if(data.getInt("version")==2){JSONArray weeks=data.getJSONArray("weeks");for(int i=0;i<weeks.length();i++){JSONObject row=weeks.getJSONObject(i);db.execSQL("INSERT INTO weeks VALUES(?,?)",new Object[]{row.getString("week"),row.getInt("rate_cents")});}}
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    private static String csvCell(String value) {
        String trimmed=value.replaceFirst("^\\s+","");
        if((!trimmed.isEmpty() && "=+-@".indexOf(trimmed.charAt(0))>=0) || value.startsWith("\t") || value.startsWith("\r") || value.startsWith("\n")) value="'"+value;
        return "\""+value.replace("\"","\"\"")+"\"";
    }
    public synchronized String csv(String month)throws JSONException{return csv("monthly",month);}
    public synchronized String csv(String frequency,String key)throws JSONException {
        JSONObject data=period(frequency,key);JSONArray entries=data.getJSONArray("entries");
        StringBuilder out=new StringBuilder("\ufeffFecha;Horas;Tarifa (EUR/h);Nota;Día cobrado\r\n");
        for(int i=0;i<entries.length();i++) {
            JSONObject row=entries.getJSONObject(i);
            out.append(row.getString("day")).append(';').append(Domain.hours(row.getInt("minutes")).replace('.',','))
                .append(';').append(String.format(java.util.Locale.ROOT,"%.2f",row.getInt("rate_cents")/100.0).replace('.',','))
                .append(';').append(csvCell(row.getString("note"))).append(';').append(row.getInt("paid")==1?"Sí":"No").append("\r\n");
        }
        return out.append("\r\nTOTAL;").append(Domain.hours(data.getInt("minutes")).replace('.',','))
            .append(";Importe (EUR);").append(String.format(java.util.Locale.ROOT,"%.2f",data.getLong("total")/100.0).replace('.',',')).append("\r\n").toString();
    }
}

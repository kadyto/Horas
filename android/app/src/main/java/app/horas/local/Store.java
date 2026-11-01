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
    Store(Context context, String name) { super(context, name, null, 1); setWriteAheadLoggingEnabled(true); }

    @Override public void onConfigure(SQLiteDatabase db) { db.setForeignKeyConstraintsEnabled(true); }
    @Override public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK(id=1),default_minutes INTEGER NOT NULL CHECK(default_minutes BETWEEN 30 AND 1440 AND default_minutes%30=0),default_rate_cents INTEGER NOT NULL CHECK(default_rate_cents BETWEEN 0 AND 1000000))");
        db.execSQL("INSERT INTO settings VALUES(1,120,0)");
        db.execSQL("CREATE TABLE months(month TEXT PRIMARY KEY,rate_cents INTEGER NOT NULL CHECK(rate_cents BETWEEN 0 AND 1000000),paid INTEGER NOT NULL DEFAULT 0 CHECK(paid IN(0,1)))");
        db.execSQL("CREATE TABLE entries(day TEXT PRIMARY KEY,month TEXT NOT NULL REFERENCES months(month),minutes INTEGER NOT NULL CHECK(minutes BETWEEN 30 AND 1440 AND minutes%30=0),note TEXT NOT NULL DEFAULT '',revision INTEGER NOT NULL)");
        db.execSQL("CREATE INDEX entries_month ON entries(month)");
    }
    @Override public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        throw new IllegalStateException("Versión de base de datos no compatible.");
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
        return one("SELECT default_minutes,default_rate_cents FROM settings WHERE id=1");
    }
    private void ensureMonth(String month) throws JSONException {
        getWritableDatabase().execSQL("INSERT OR IGNORE INTO months(month,rate_cents) VALUES(?,?)", new Object[]{month,preferences().getInt("default_rate_cents")});
    }
    public synchronized JSONObject entry(String day) throws JSONException {
        return one("SELECT * FROM entries WHERE day=?", Domain.day(day));
    }
    public synchronized JSONObject month(String month) throws JSONException {
        Domain.month(month);
        JSONObject prefs = preferences();
        JSONObject data = one("SELECT * FROM months WHERE month=?", month);
        if (data == null) data = new JSONObject().put("month",month).put("rate_cents",prefs.getInt("default_rate_cents")).put("paid",0);
        JSONArray entries = many("SELECT * FROM entries WHERE month=? ORDER BY day",month);
        int minutes = 0;
        for(int i=0;i<entries.length();i++) minutes += entries.getJSONObject(i).getInt("minutes");
        return data.put("entries",entries).put("minutes",minutes).put("days",entries.length())
            .put("total",Domain.earnings(minutes,data.getInt("rate_cents"))).put("prefs",prefs);
    }
    public synchronized JSONArray history(int year) throws JSONException {
        if(year<2000 || year>2100) throw new IllegalArgumentException("El año debe estar entre 2000 y 2100.");
        JSONArray result = new JSONArray();
        for(int month=1;month<=12;month++) result.put(month(String.format(java.util.Locale.ROOT,"%04d-%02d",year,month)));
        return result;
    }
    public synchronized boolean quick(String day, int minutes) throws JSONException {
        Domain.day(day); Domain.minutes(minutes);
        SQLiteDatabase db = getWritableDatabase(); db.beginTransaction();
        try {
            ensureMonth(day.substring(0,7));
            boolean created = entry(day) == null;
            if(created) {
                db.execSQL("INSERT INTO entries VALUES(?,?,?,?,?)",new Object[]{day,day.substring(0,7),minutes,"",newRevision()});
                db.execSQL("UPDATE months SET paid=0 WHERE month=?",new Object[]{day.substring(0,7)});
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
            if(old==null) db.insertOrThrow("entries",null,values); else db.update("entries",values,"day=?",new String[]{day});
            if(old==null || old.getInt("minutes")!=minutes) db.execSQL("UPDATE months SET paid=0 WHERE month=?",new Object[]{day.substring(0,7)});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    public synchronized void delete(String day,long revision) {
        Domain.day(day); SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
            if(db.delete("entries","day=? AND revision=?",new String[]{day,String.valueOf(revision)})!=1)
                throw new IllegalArgumentException("El registro ha cambiado o ya se ha eliminado.");
            db.execSQL("UPDATE months SET paid=0 WHERE month=?",new Object[]{day.substring(0,7)});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    public synchronized void setPreferences(int minutes,String rate) {
        Domain.minutes(minutes); int cents=Domain.rate(rate);
        getWritableDatabase().execSQL("UPDATE settings SET default_minutes=?,default_rate_cents=? WHERE id=1",new Object[]{minutes,cents});
    }
    public synchronized void setRate(String month,String rate) throws JSONException {
        Domain.month(month); int cents=Domain.rate(rate);
        SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
            ensureMonth(month);
            db.execSQL("UPDATE months SET paid=CASE WHEN rate_cents!=? THEN 0 ELSE paid END,rate_cents=? WHERE month=?",new Object[]{cents,cents,month});
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    public synchronized void setPaid(String month,int paid,int expectedMinutes,int expectedRate) throws JSONException {
        Domain.month(month);
        if(paid!=0 && paid!=1) throw new IllegalArgumentException("El estado de cobro no es válido.");
        SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
            JSONObject data=month(month);
            if(data.getInt("days")==0) throw new IllegalArgumentException("Añade horas antes de marcar el mes como cobrado.");
            if(data.getInt("minutes")!=expectedMinutes || data.getInt("rate_cents")!=expectedRate)
                throw new IllegalArgumentException("El total ha cambiado. Revisa el mes antes de marcar el cobro.");
            db.execSQL("UPDATE months SET paid=? WHERE month=?",new Object[]{paid,month}); db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    public synchronized JSONObject backup() throws JSONException {
        SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
            JSONObject data=new JSONObject().put("format","horas").put("version",1).put("settings",preferences())
                .put("months",many("SELECT month,rate_cents,paid FROM months ORDER BY month"))
                .put("entries",many("SELECT day,minutes,note FROM entries ORDER BY day"));
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
        if(!"horas".equals(data.optString("format")) || strictInt(data,"version",1,1,1)!=1)
            throw new IllegalArgumentException("La copia no tiene un formato compatible con Horas.");
        JSONObject prefs=data.getJSONObject("settings");
        strictInt(prefs,"default_minutes",30,1440,30); strictInt(prefs,"default_rate_cents",0,1000000,1);
        JSONArray months=data.getJSONArray("months"),entries=data.getJSONArray("entries");
        if(months.length()>1212 || entries.length()>37000) throw new IllegalArgumentException("La copia contiene demasiados registros.");
        Set<String> seenMonths=new HashSet<>(),seenDays=new HashSet<>();
        for(int i=0;i<months.length();i++) {
            JSONObject row=months.getJSONObject(i); String month=Domain.month(row.getString("month"));
            if(!seenMonths.add(month)) throw new IllegalArgumentException("La copia contiene meses duplicados.");
            strictInt(row,"rate_cents",0,1000000,1); strictInt(row,"paid",0,1,1);
        }
        for(int i=0;i<entries.length();i++) {
            JSONObject row=entries.getJSONObject(i); String day=Domain.day(row.getString("day"));
            if(!seenDays.add(day) || !seenMonths.contains(day.substring(0,7))) throw new IllegalArgumentException("La copia contiene días duplicados o sin mes asociado.");
            strictInt(row,"minutes",30,1440,30);
            if(!(row.get("note") instanceof String)) throw new IllegalArgumentException("La copia contiene una nota no válida.");
            String note=row.getString("note");
            if(note.codePointCount(0,note.length())>500) throw new IllegalArgumentException("La copia contiene una nota demasiado larga.");
        }
    }
    public synchronized void restore(JSONObject data) throws JSONException {
        validateBackup(data); SQLiteDatabase db=getWritableDatabase(); db.beginTransaction();
        try {
            db.delete("entries",null,null); db.delete("months",null,null);
            JSONObject prefs=data.getJSONObject("settings");
            setPreferences(prefs.getInt("default_minutes"),java.math.BigDecimal.valueOf(prefs.getInt("default_rate_cents"),2).toPlainString());
            JSONArray months=data.getJSONArray("months"),entries=data.getJSONArray("entries");
            for(int i=0;i<months.length();i++) {
                JSONObject row=months.getJSONObject(i);
                db.execSQL("INSERT INTO months VALUES(?,?,?)",new Object[]{row.getString("month"),row.getInt("rate_cents"),row.getInt("paid")});
            }
            for(int i=0;i<entries.length();i++) {
                JSONObject row=entries.getJSONObject(i); String day=row.getString("day");
                db.execSQL("INSERT INTO entries VALUES(?,?,?,?,?)",new Object[]{day,day.substring(0,7),row.getInt("minutes"),row.getString("note"),newRevision()});
            }
            db.setTransactionSuccessful();
        } finally { db.endTransaction(); }
    }
    private static String csvCell(String value) {
        String trimmed=value.replaceFirst("^\\s+","");
        if((!trimmed.isEmpty() && "=+-@".indexOf(trimmed.charAt(0))>=0) || value.startsWith("\t") || value.startsWith("\r") || value.startsWith("\n")) value="'"+value;
        return "\""+value.replace("\"","\"\"")+"\"";
    }
    public synchronized String csv(String month) throws JSONException {
        JSONObject data=month(month); int rate=data.getInt("rate_cents"); JSONArray entries=data.getJSONArray("entries");
        StringBuilder out=new StringBuilder("\ufeffFecha;Horas;Tarifa (EUR/h);Nota;Mes cobrado\r\n");
        for(int i=0;i<entries.length();i++) {
            JSONObject row=entries.getJSONObject(i);
            out.append(row.getString("day")).append(';').append(Domain.hours(row.getInt("minutes")).replace('.',','))
                .append(';').append(String.format(java.util.Locale.ROOT,"%.2f",rate/100.0).replace('.',','))
                .append(';').append(csvCell(row.getString("note"))).append(';').append(data.getInt("paid")==1?"Sí":"No").append("\r\n");
        }
        return out.append("\r\nTOTAL;").append(Domain.hours(data.getInt("minutes")).replace('.',','))
            .append(";Importe (EUR);").append(String.format(java.util.Locale.ROOT,"%.2f",data.getLong("total")/100.0).replace('.',',')).append("\r\n").toString();
    }
}

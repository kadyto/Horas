package app.horas.local;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.YearMonth;
import java.util.regex.Pattern;

/** Integer minutes and cents, with the same rounding and date limits as the web app. */
public final class Domain {
    private Domain() {}
    public static String month(String value) {
        try {
            if (value == null || !Pattern.matches("[0-9]{4}-[0-9]{2}", value)) throw new IllegalArgumentException();
            YearMonth parsed = YearMonth.parse(value);
            if (parsed.getYear() < 2000 || parsed.getYear() > 2100) throw new IllegalArgumentException();
            return value;
        } catch (Exception error) { throw new IllegalArgumentException("El mes debe estar entre enero de 2000 y diciembre de 2100."); }
    }
    public static String day(String value) {
        try {
            if (value == null || !Pattern.matches("[0-9]{4}-[0-9]{2}-[0-9]{2}", value)) throw new IllegalArgumentException();
            LocalDate.parse(value);
            month(value.substring(0, 7));
            return value;
        } catch (Exception error) { throw new IllegalArgumentException("La fecha no es válida."); }
    }
    public static int minutes(int value) {
        if (value < 30 || value > 1440 || value % 30 != 0)
            throw new IllegalArgumentException("Las horas deben ir de 0,5 a 24, en intervalos de media hora.");
        return value;
    }
    public static int rate(String value) {
        try {
            BigDecimal rate = new BigDecimal(value.trim().replace(',', '.'));
            if (rate.signum() < 0 || rate.compareTo(new BigDecimal("10000")) > 0) throw new ArithmeticException();
            return rate.movePointRight(2).intValueExact();
        } catch (Exception error) {
            throw new IllegalArgumentException("La tarifa debe estar entre 0 y 10.000 €, con un máximo de dos decimales.");
        }
    }
    public static long earnings(long minutes, int cents) {
        return BigDecimal.valueOf(minutes).multiply(BigDecimal.valueOf(cents))
            .divide(BigDecimal.valueOf(60), 0, RoundingMode.HALF_UP).longValueExact();
    }
    public static String hours(int minutes) {
        return BigDecimal.valueOf(minutes).divide(BigDecimal.valueOf(60)).stripTrailingZeros().toPlainString();
    }
}

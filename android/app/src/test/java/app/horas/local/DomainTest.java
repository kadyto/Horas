package app.horas.local;

import org.junit.Test;
import static org.junit.Assert.*;

public class DomainTest {
    @Test public void moneyRoundsOncePerMonth() {
        assertEquals(4463,Domain.earnings(210,1275));
        assertEquals(1001,Domain.earnings(60,1001));
        assertEquals(501,Domain.earnings(30,1001));
    }
    @Test public void acceptsHalfHoursAndDecimalComma() {
        assertEquals(90,Domain.minutes(90));
        assertEquals("1.5",Domain.hours(90));
        assertEquals(1275,Domain.rate("12,75"));
        assertEquals(0,Domain.rate("0"));
    }
    @Test public void rejectsFractionsSmallerThanHalfAnHour() {
        for(int minutes:new int[]{0,15,61,1450}) {
            try{Domain.minutes(minutes);fail("Accepted invalid minutes");}catch(IllegalArgumentException expected){}
        }
    }
    @Test public void rejectsInvalidRates() {
        for(String rate:new String[]{"NaN","-1","10000.01","1.001"}) {
            try{Domain.rate(rate);fail("Accepted invalid rate");}catch(IllegalArgumentException expected){}
        }
    }
    @Test public void validatesRealDatesAndYearLimits() {
        assertEquals("2028-02-29",Domain.day("2028-02-29"));
        for(String day:new String[]{"2026-02-29","2026-13-01","1999-12-01","2101-01-01","26-01-01"}) {
            try{Domain.day(day);fail("Accepted invalid date");}catch(IllegalArgumentException expected){}
        }
    }
    @Test public void weeksCrossMonthsAndIsoYears() {
        assertEquals("2020-12-28",Domain.weekStart("2021-01-01"));
        assertEquals("2026-10-26",Domain.weekStart("2026-11-01"));
        assertEquals(53,Domain.yearWeeks(2020).size());
        assertEquals(52,Domain.yearWeeks(2021).size());
        assertTrue(Domain.yearWeeks(2020).contains("2020-12-28"));
        assertFalse(Domain.yearWeeks(2021).contains("2020-12-28"));
        assertEquals("1999-12-27",Domain.week("1999-12-27"));
    }
}

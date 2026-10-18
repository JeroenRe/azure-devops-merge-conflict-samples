using System;

namespace Samples.Src
{
    // Old report formatter, scheduled for removal.
    public static class Legacy
    {
        public static string FormatReport(string title, int count)
        {
            return title + ": " + count + " items";
        }

        public static string FormatTotal(int total)
        {
            return "Total = " + total;
        }
    }
}

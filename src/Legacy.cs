using System;

namespace Samples.Src
{
    // Old report formatter, scheduled for removal.
    public static class Legacy
    {
        public static string FormatReport(string title, int count)
        {
            return title + ": " + count + " items (" + DateTime.Now.Year + ")";
        }

        public static string FormatTotal(int total)
        {
            return "Total: " + total;
        }
    }
}

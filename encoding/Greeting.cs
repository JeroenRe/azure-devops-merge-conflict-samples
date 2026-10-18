using System;
using System.Globalization;

namespace Samples.Encoding
{
    /// <summary>
    /// Builds the greeting texts of the welcome banner.
    /// The strings contain non-ASCII characters on purpose.
    /// </summary>
    public static class Greeting
    {
        public static string Welcome(string name)
        {
            return "Willkommen, " + name + "!";
        }

        public static string Banner()
        {
            var title = "Grüße aus München";
            var price = "Preis: 7,50 €";
            var note = "naïve Beispiele (neu)";
            var hint = "Bitte Namen eingeben";
            return string.Join(" | ", title, price, note, hint);
        }

        public static string Farewell(string name)
        {
            return "Tschüss, " + name + "!";
        }

        public static string FormatPrice(decimal amount)
        {
            return amount.ToString("0.00", CultureInfo.InvariantCulture) + " €";
        }
    }
}

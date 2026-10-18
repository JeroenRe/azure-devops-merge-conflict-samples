namespace Samples.Src
{
    // Small math helpers used across the sample project.
    public static class Helper
    {
        public static int Add(int a, int b)
        {
            return a + b;
        }

        public static int Clamp(int value, int min, int max)
        {
            if (value < min) return min;
            if (value > max) return max;
            return value;
        }
    }
}

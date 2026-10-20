using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace EaStandalone.AuthHost;

internal static class Program
{
    [STAThread]
    private static void Main()
    {
        ApplicationConfiguration.Initialize();
        string? authorizationUrl = Console.In.ReadLine();
        if (string.IsNullOrWhiteSpace(authorizationUrl))
        {
            Environment.ExitCode = 2;
            return;
        }
        Application.Run(new LoginForm(authorizationUrl));
    }

    private sealed class LoginForm : Form
    {
        private readonly string authorizationUrl;
        private readonly WebView2 browser = new() { Dock = DockStyle.Fill };
        private readonly Label status = new()
        {
            Dock = DockStyle.Top,
            Height = 28,
            Text = "Starting secure sign-in…",
            TextAlign = ContentAlignment.MiddleLeft,
            Padding = new Padding(8, 0, 0, 0),
        };
        private bool completed;

        internal LoginForm(string authorizationUrl)
        {
            this.authorizationUrl = authorizationUrl;
            Text = "Sign in to EA";
            Width = 540;
            Height = 760;
            StartPosition = FormStartPosition.CenterScreen;
            Controls.Add(browser);
            Controls.Add(status);
            Shown += InitializeBrowser;
            FormClosed += (_, _) => { if (!completed) Environment.ExitCode = 3; };
        }

        private async void InitializeBrowser(object? sender, EventArgs args)
        {
            try
            {
                string profile = Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "EAStandaloneLauncher",
                    "WebView2");
                CoreWebView2Environment environment = await CoreWebView2Environment.CreateAsync(null, profile);
                await browser.EnsureCoreWebView2Async(environment);
                browser.CoreWebView2.Settings.AreDevToolsEnabled = false;
                browser.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
                browser.CoreWebView2.NavigationStarting += NavigationStarting;
                browser.CoreWebView2.NavigationCompleted += NavigationCompleted;
                browser.CoreWebView2.SourceChanged += SourceChanged;
                browser.CoreWebView2.NewWindowRequested += NewWindowRequested;
                browser.CoreWebView2.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All);
                browser.CoreWebView2.WebResourceRequested += WebResourceRequested;
                browser.CoreWebView2.Navigate(authorizationUrl);
            }
            catch
            {
                Environment.ExitCode = 4;
                Close();
            }
        }

        private void NavigationStarting(object? sender, CoreWebView2NavigationStartingEventArgs args)
        {
            if (TryComplete(args.Uri))
                args.Cancel = true;
        }

        private void NewWindowRequested(object? sender, CoreWebView2NewWindowRequestedEventArgs args)
        {
            if (TryComplete(args.Uri))
                args.Handled = true;
        }

        private void WebResourceRequested(object? sender, CoreWebView2WebResourceRequestedEventArgs args)
        {
            TryComplete(args.Request.Uri);
        }

        private void SourceChanged(object? sender, CoreWebView2SourceChangedEventArgs args)
        {
            TryComplete(browser.Source?.AbsoluteUri);
        }

        private void NavigationCompleted(object? sender, CoreWebView2NavigationCompletedEventArgs args)
        {
            if (completed)
                return;
            Uri? current = browser.Source;
            status.Text = current is null
                ? "Waiting for EA…"
                : $"EA sign-in: {current.Host}{current.AbsolutePath}";
        }

        private bool TryComplete(string? value)
        {
            if (completed || string.IsNullOrWhiteSpace(value))
                return false;
            if (!Uri.TryCreate(value, UriKind.Absolute, out Uri? uri))
                return false;
            if (!uri.Scheme.Equals("qrc", StringComparison.OrdinalIgnoreCase) ||
                !uri.AbsolutePath.Equals("/html/login_successful.html", StringComparison.OrdinalIgnoreCase))
                return false;
            completed = true;
            Console.Out.WriteLine(value);
            Console.Out.Flush();
            BeginInvoke(Close);
            return true;
        }
    }
}

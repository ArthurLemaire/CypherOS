# The JavaScript bridge is reached by name from the page.
-keepclassmembers class io.github.nanomuse.app.Bridge {
    @android.webkit.JavascriptInterface <methods>;
}
-dontwarn okhttp3.**
-dontwarn org.bouncycastle.**
-dontwarn org.conscrypt.**
-dontwarn org.openjsse.**

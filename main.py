import os
import sys
import threading
import time

# 确保导入路径
sys.path.insert(0, os.path.dirname(__file__))

from app import app, db

def start_flask():
    app.run(host='127.0.0.1', port=5000, debug=False)

if __name__ == '__main__':
    # 启动 Flask 线程
    flask_thread = threading.Thread(target=start_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # 尝试使用 Kivy WebView 打开页面
    try:
        from kivy.app import App
        from kivy.uix.widget import Widget
        from jnius import autoclass
        from android.runnable import run_on_ui_thread

        Activity = autoclass('org.kivy.android.PythonActivity').mActivity
        WebView = autoclass('android.webkit.WebView')
        WebViewClient = autoclass('android.webkit.WebViewClient')

        class WebViewApp(App):
            def build(self):
                self.create_webview()
                return Widget()

            @run_on_ui_thread
            def create_webview(self):
                webview = WebView(Activity)
                webview.getSettings().setJavaScriptEnabled(True)
                webview.getSettings().setDomStorageEnabled(True)
                webview.setWebViewClient(WebViewClient())
                webview.loadUrl('http://127.0.0.1:5000')
                Activity.setContentView(webview)

        WebViewApp().run()
    except Exception as e:
        print("Fallback to basic thread keepalive:", e)
        while True:
            time.sleep(1)

[app]
title = 人情礼金记账
package.name = giftbookkeeping
package.domain = com.giftbookkeeping.app
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,html,css,js,db
source.include_patterns = templates/*,gift_bookkeeping.db

version = 1.0.0
requirements = python3,flask,flask_sqlalchemy,flask_login,cn2num,kivy,pyjnius

orientation = portrait
fullscreen = 0

# Android specific
android.permissions = INTERNET, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 21
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a

[buildozer]
log_level = 2
warn_on_root = 1

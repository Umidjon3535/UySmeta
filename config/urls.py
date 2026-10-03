"""URL'lar asl saytdagidek (oxirgi "/" siz) — eski havolalar va Telegram webhook o'zgarmaydi."""

from django.urls import path
from django.views.generic import RedirectView

from core.views import accounts, admin_panel, design, estimates, master_cabinet, masters, orders, pages, shops, support, wallet

urlpatterns = [
    path("", estimates.home, name="home"),
    path("smetalar", estimates.estimates_list, name="estimates"),
    path("smeta/<str:public_id>", estimates.estimate_detail, name="estimate"),
    path("smeta/<str:public_id>/pdf", wallet.estimate_pdf_view, name="estimate_pdf"),
    path("ustalar", masters.masters_list, name="masters"),
    path("ustalar/<int:master_id>", masters.master_detail, name="master"),
    path("usta-bolish", masters.become_master, name="become_master"),
    path("narxlar", orders.pricing, name="pricing"),
    path("buyurtma/<int:order_id>", orders.order_detail, name="order"),
    path("biz-haqimizda", pages.about, name="about"),
    path("dokonlar", shops.shops_list, name="shops"),
    path("dokonlar/<int:shop_id>", shops.shop_detail, name="shop"),
    path("oferta", pages.oferta, name="oferta"),
    path("ai-loyiha", design.design_form, name="design"),
    path("ai-loyiha/<str:public_id>", design.design_detail, name="design_result"),
    path("ai-loyiha/<str:public_id>/pdf", wallet.design_pdf_view, name="design_pdf"),
    path("ai-loyiha/<str:public_id>/3d", wallet.design_3d_view, name="design_3d"),
    path("ai-loyiha/<str:public_id>/real", wallet.design_real_view, name="design_real"),
    path("hamyon", wallet.wallet_view, name="wallet"),
    path("kirish", accounts.login_view, name="login"),
    path("kirish/telegram", accounts.telegram_login_view, name="telegram_login"),
    path("kirish/telegram/<str:token>", accounts.telegram_login_finish, name="telegram_login_finish"),
    path("api/telegram-kirish/<str:token>", accounts.telegram_login_status, name="telegram_login_status"),
    path("api/yordam", support.support_api, name="support_api"),
    path("royxat", accounts.register_view, name="register"),
    path("parolni-tiklash", accounts.reset_view, name="reset_password"),
    path("chiqish", accounts.logout_view, name="logout"),
    path("profil", accounts.profile_view, name="profile"),
    path("usta/sorovlar", master_cabinet.master_requests, name="master_requests"),
    path("usta/portfolio", master_cabinet.master_portfolio, name="master_portfolio"),
    path("admin", admin_panel.admin_view, name="admin"),
    # API
    path("api/hisob", estimates.api_calculate, name="api_calculate"),
    path("api/ai/tahlil", estimates.api_analyze, name="api_analyze"),
    path("api/ai-loyiha/<str:public_id>", design.design_status, name="api_design_status"),
    path("api/ai-loyiha/<str:public_id>/real", wallet.design_real_status, name="api_design_real_status"),
    path("api/ai-loyiha/<str:public_id>/burchaklar", design.design_corners, name="api_design_corners"),
    path("api/ai-loyiha/<str:public_id>/kompozit", design.design_guide, name="api_design_guide"),
    path("api/uploads/<str:name>", pages.uploaded_file, name="upload"),
    path("admin/hujjat/<str:name>", admin_panel.master_document, name="master_document"),
    path("api/telegram/webhook", pages.telegram_webhook, name="telegram_webhook"),
    # SEO va PWA
    path("sitemap.xml", pages.sitemap),
    path("robots.txt", pages.robots),
    path("manifest.webmanifest", pages.manifest),
    path("sw.js", pages.service_worker, name="service_worker"),
    path("offline", pages.offline, name="offline"),
    path("icon.svg", RedirectView.as_view(url="/static/icon.svg", permanent=True)),
    path("favicon.ico", RedirectView.as_view(url="/static/icon.svg", permanent=True)),
]

handler404 = "core.views.pages.page_not_found"
handler500 = "core.views.pages.server_error"

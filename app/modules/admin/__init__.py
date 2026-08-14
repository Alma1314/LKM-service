"""后台管理子系统（仅 account_level=admin 可访问）。

认证采用独立的 httpOnly Cookie 会话（admin_session / admin_refresh），
与前台 localStorage+Bearer 双轨并存。权限单一事实源在后端 get_current_admin。
"""

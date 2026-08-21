from app.db.models import Achievement, ExchangeItem, UserBehaviorStat, UserTaskProgress


def test_new_models_defined():
    # 仅验证模型能构造并映射到各自表名（create_all 在建表后由 init_db 兜底）
    assert Achievement.__tablename__ == "achievements"
    assert UserBehaviorStat.__tablename__ == "user_behavior_stats"
    assert ExchangeItem.__tablename__ == "exchange_items"
    assert UserTaskProgress.__tablename__ == "user_task_progress"

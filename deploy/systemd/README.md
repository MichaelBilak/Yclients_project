# Systemd Units

Шаблоны рассчитаны на установку проекта в `/opt/yclients_bi_system`.

Пример для пользователя `deploy`:

```bash
sudo cp deploy/systemd/yclients-api@.service /etc/systemd/system/
sudo cp deploy/systemd/yclients-sync-incremental@.service /etc/systemd/system/
sudo cp deploy/systemd/yclients-sync-incremental@.timer /etc/systemd/system/
sudo cp deploy/systemd/yclients-sync-full@.service /etc/systemd/system/
sudo cp deploy/systemd/yclients-sync-full@.timer /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable --now yclients-api@deploy.service
sudo systemctl enable --now yclients-sync-incremental@deploy.timer
sudo systemctl enable --now yclients-sync-full@deploy.timer
```

Проверка:

```bash
systemctl status yclients-api@deploy.service
systemctl list-timers | grep yclients-sync
journalctl -u yclients-api@deploy.service -f
```

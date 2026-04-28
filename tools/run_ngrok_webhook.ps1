param(
    [string]$LocalHost = "127.0.0.1",
    [int]$Port = 8088
)

Write-Host "Iniciando ngrok para Telegram webhook..."
Write-Host "Endpoint local: http://$LocalHost`:$Port/telegram/webhook"
Write-Host "Cuando ngrok esté activo, copia la URL pública HTTPS y configura setWebhook en BotFather."
Write-Host ""

ngrok http "$LocalHost`:$Port"


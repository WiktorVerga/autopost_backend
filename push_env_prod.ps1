Get-Content .env.prod | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith('#')) { return }
  $name, $value = $line -split '=', 2
  if (-not $value) { return }   # salta le variabili vuote
  aws ssm put-parameter --profile autopost --region eu-central-1 `
    --name "/autopost/prod/$name" --type SecureString --value "$value" --overwrite | Out-Null
  Write-Host "OK $name"
}

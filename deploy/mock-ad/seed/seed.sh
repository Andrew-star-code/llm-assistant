#!/usr/bin/env bash
# Тестовые данные mock-AD (§6.7): русские ФИО (один без отчества), отделы в department,
# должности, телефоны, руководители, фото; одна отключённая учётка; группы для access_group.
set -euo pipefail

BASE="DC=$(echo "${MOCK_AD_REALM:-CORP.LOCAL}" | tr '[:upper:]' '[:lower:]' | sed 's/\./,DC=/g')"
SAM=/var/lib/samba/private/sam.ldb
USER_PASSWORD="${MOCK_AD_USER_PASSWORD:-Passw0rd!}"
SVC_PASSWORD="${MOCK_AD_SVC_PASSWORD:?задайте MOCK_AD_SVC_PASSWORD}"

# Политика блокировки AD строже нашей не бывает: наш порог (5) должен быть ниже порога AD (§6.2).
samba-tool domain passwordsettings set --account-lockout-threshold=10 \
  --account-lockout-duration=15 --reset-account-lockout-after=15 --max-pwd-age=0 >/dev/null

samba-tool ou create "OU=Staff,${BASE}" >/dev/null
samba-tool ou create "OU=Service Accounts,${BASE}" >/dev/null

samba-tool user create svc-ai-assistant "${SVC_PASSWORD}" --use-username-as-cn \
  --userou="OU=Service Accounts" --description="Сервисная учётка ИИ-ассистента (только чтение)" >/dev/null
samba-tool user setexpiry svc-ai-assistant --noexpiry >/dev/null

# login | Фамилия | Имя | Отчество | Должность | Отдел | Тел. | Моб. | Табельный | Руководитель
USERS=(
  "ivanov|Иванов|Иван|Петрович|Руководитель ИТ-отдела|ИТ-отдел|+7 (495) 100-10-01|+7 (900) 100-10-01|0001|"
  "kim|Ким|Александр||Инженер технической поддержки|ИТ-отдел|+7 (495) 100-10-02|+7 (900) 100-10-02|0002|ivanov"
  "smirnova|Смирнова|Анна|Викторовна|Главный бухгалтер|Бухгалтерия|+7 (495) 100-20-01|+7 (900) 100-20-01|0003|"
  "petrov|Петров|Сергей|Алексеевич|Бухгалтер|Бухгалтерия|+7 (495) 100-20-02||0004|smirnova"
  "sidorova|Сидорова|Елена|Николаевна|Юрисконсульт|Юридический отдел|+7 (495) 100-30-01|+7 (900) 100-30-01|0005|"
  "kuznetsov|Кузнецов|Дмитрий|Олегович|Менеджер по продажам|Отдел продаж|+7 (495) 100-40-01||0006|"
  "volkov|Волков|Павел|Игоревич|Менеджер по закупкам|Отдел закупок|+7 (495) 100-50-01||0007|"
)

for row in "${USERS[@]}"; do
  IFS='|' read -r login last first middle title dept phone mobile empid manager <<<"${row}"
  samba-tool user create "${login}" "${USER_PASSWORD}" --use-username-as-cn --userou="OU=Staff" \
    --surname="${last}" --given-name="${first}" --job-title="${title}" --department="${dept}" \
    --company="ООО «Корпорация»" --mail-address="${login}@corp.local" \
    --telephone-number="${phone}" --physical-delivery-office="Москва, офис 1" >/dev/null
  samba-tool user setexpiry "${login}" --noexpiry >/dev/null

  dn="CN=${login},OU=Staff,${BASE}"
  display="${last} ${first}${middle:+ ${middle}}"
  {
    echo "dn: ${dn}"
    echo "changetype: modify"
    echo "replace: displayName"
    echo "displayName: ${display}"
    echo "-"
    echo "replace: employeeID"
    echo "employeeID: ${empid}"
    if [ -n "${middle}" ]; then
      echo "-"; echo "replace: middleName"; echo "middleName: ${middle}"
    fi
    if [ -n "${mobile}" ]; then
      echo "-"; echo "replace: mobile"; echo "mobile: ${mobile}"
    fi
    if [ -n "${manager}" ]; then
      echo "-"; echo "replace: manager"; echo "manager: CN=${manager},OU=Staff,${BASE}"
    fi
    if [ -f "/seed/photos/${login}.jpg" ]; then
      echo "-"; echo "replace: thumbnailPhoto"; echo "thumbnailPhoto:: $(base64 -w0 "/seed/photos/${login}.jpg")"
    fi
  } | ldbmodify -H "${SAM}" >/dev/null
done

samba-tool user disable kuznetsov >/dev/null

# Группы для необязательных access_group и group_roles. AI-Admins вложена в AI-Assistant-Users:
# ivanov состоит только в AI-Admins и проходит access_group через вложенность (правило 1.2.840.113556.1.4.1941).
# volkov — ни в одной группе: при заданной access_group не входит.
samba-tool group add AI-Assistant-Users --description="Доступ к ИИ-ассистенту" >/dev/null
samba-tool group add AI-Admins --description="Администраторы ИИ-ассистента" >/dev/null
samba-tool group addmembers AI-Assistant-Users "AI-Admins,kim,smirnova,petrov,sidorova,kuznetsov" >/dev/null
samba-tool group addmembers AI-Admins ivanov >/dev/null

echo "mock-ad: создано пользователей: ${#USERS[@]} (+ svc-ai-assistant)"

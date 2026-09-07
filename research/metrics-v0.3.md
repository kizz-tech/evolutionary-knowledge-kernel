# H1–H4: измерительный инструментарий v0.3

Статус: реализованы локальные контракты измерений и детерминированный rehearsal. Это дополнение к [протоколу v0.1](protocol-v0.1.md), а не полученный научный результат. Код находится в `ekk.experiments`; механизм capability — в `ekk.capabilities`.

## Как использовать

`RunRecord` описывает отдельную задачу внутри заранее назначенной независимой траектории. `Costs` требует все составляющие стоимости; неизвестное значение нельзя подменять нулём. Нулевые цены rehearsal означают отсутствие модельных вызовов; временные нули — сценарные значения, а не измеренный benchmark.

Создать `ExperimentLedger()`, добавить проверенные `RunRecord` через `add`, получить `summary()` и записать новый артефакт через `write(path)`. `RunRecord.from_mapping` принимает JSON-совместимое представление, `ExperimentLedger.read` заново проверяет записи и пересчитывает производную сводку. Существующий файл не перезаписывается. Машинный формат JSON используется для измерений, повествовательные исследовательские документы остаются Markdown.

Обязательны версия протокола, гипотеза, task family/task ID, trajectory/condition/split, replica/seed, точные model ID/revision, версии harness/kernel/compiler/evaluator, изолированные environment IDs, разрешённые snapshots/policy versions и fingerprints знания/инструментов. Для неопределённой backend revision следует записать явное `unavailable:...` и раскрыть ограничение; стабильность alias не предполагается.

Стоимость включает human minutes, tokens, фактическую цену модели, tool/compute, wall seconds, время создания и поддержки среды. Не складывать минуты с деньгами. Не записывать полную стоимость создания среды заново на каждой задаче: отнести её один раз к задаче создания или использовать заранее описанное распределение. Сводка суммирует заявленные составляющие; валюты не конвертирует.

Успех требует независимой проверки. Failure, stopped, omitted и no-change требуют причины и остаются в данных. Неуспешные/остановленные назначения не удаляются ради положительной сводки. Все назначенные траектории должен внести вызывающий harness: ledger не может обнаружить скрытое от него назначение.

## Метрики и сравнения

| Вопрос | Запись и интерпретация |
| --- | --- |
| H1: развитие среды против памяти | B/D и дополнительные A/C задаются condition; одна H1-группа сохраняет model/revision/protocol/harness/evaluator. Смена модели — отдельный experiment ID. Качество сравнивается с полной стоимостью, а не только поздней скоростью |
| H2: текст против executable knowledge | Одинаковое исходное знание и допустимые snapshots фиксируются до запуска. Capability digest отдельно от knowledge digests. Разницу ошибок и полной стоимости оценивают на сопоставимых задачах; ledger сам не устанавливает эквивалентность наборов знания |
| H3: федерация | Required/covered authorized context, false inclusions, context bytes, compile seconds, denied disclosures и authority confusion. Изоляция, федерация и разрешённый oracle — разные заранее заданные conditions. Запрещённый источник не входит в required context |
| H4: удаление обвязки | `ScaffoldItem` / `scaffold_inventory` сохраняют причину появления, модельную зависимость, maintenance, evidence, candidate и отдельный holdout. Нет произвольного composite debt score. Verified removal в инвентаре — заявление о проверке, не разрешение отключить механизм |

Learning Yield = validated reuses / reuse opportunities. Единица — заранее выделенное значимое наблюдение с возможностью применения: не считать одно и то же наблюдение несколько раз в разных task rows. Amnesia Rate = повторенные распознанные ошибки / возможности предотвратить их после доступности evidence. Каждой ошибке назначается одна первичная причина: capture, interpretation, retrieval, authorization, compilation, activation, obsolete_policy. Законно недоступное знание не входит в знаменатель; authorization означает дефект предусмотренного доступа, а не требование обойти запрет. При нулевом знаменателе ratio содержит `value: null` (N/A), числитель и знаменатель сохраняются.

Сводка показывает количество независимых trajectories отдельно от количества задач. Это описательные агрегаты, не интервалы уверенности и не causal inference. Порог неухудшения, размер выборки, бюджет, основная метрика и правила остановки фиксируются до основного запуска. Детерминированный `deterministic_rehearsal()` проверяет success/failure/no-change ветки записи без вызовов модели; каждое значение помечено `rehearsal: true`, научное подтверждение никогда не выводится автоматически.

## Граница изоляции

Ledger отклоняет повтор task ID внутри trajectory, смену condition/split/model внутри траектории, общий agent environment между независимыми траекториями и пересечение agent/evaluator environment. Записанные snapshots — декларации: фактическое ограничение filesystem, глобальных EKK config, caches и evaluator write access обеспечивает запускающая среда. Отдельное имя каталога само по себе не доказывает изоляцию. Holdout нельзя многократно использовать для настройки; раскрытый набор становится pilot, для проверки нужен новый независимый набор.

## Capability admission и повторное применение

Manifest связывает owner/code URI, version/digest, qualified basis refs, generator version, environment, privileges, verifier, rollback и reconsideration. Descriptor inert: никакой импорт Python, установка или выполнение из URI не происходит.

Доверенный host передаёт `CapabilityRuntime` callbacks `admit(operation, manifest)`, `basis_is_current(ref)`, `verifier(bytes, manifest)` и `runner(bytes, fixture)`. Эти функции не извлекаются из документа. Activate проверяет authority, digest и основания, затем независимый verifier; после проверки authority и основания проверяются снова. Runner получает те же неизменяемые bytes. Следующий run вновь проверяет authority и основания. После изменения исходного файла активированная версия использует уже проверенные bytes; для нового кода нужна новая версия и admission.

`BOUNDARY_CHECK`, `verify_boundary_check` и `run_boundary_check` — небольшой безопасный экземпляр: проверяют source disclosure, target acceptance и совпадение digest у разных synthetic fixtures. Это фиксированная функция, а не выполнение произвольного artifact code. Общий runtime доверяет host callbacks и не обещает sandbox для вредоносного Python.

Изменившееся/недоступное основание блокирует дальнейшее применение и создаёт конкретный reconsideration candidate, но не удаляет историю. `retire` требует текущего права и причины. Для safety control дополнительно нужен отдельный host-owned `retirement_verifier`: Boolean из пользовательского документа не достаточен. Возврат — повторная activation тех же проверенных bytes с актуальными правами. История runtime доступна вызывающему коду для сохранения, registry локален процессу: перезапуск требует нового admission. Это предотвращает случайное восстановление полномочий из старого receipt.

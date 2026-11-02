-- Тестовый телефонный справочник дев-стенда (§9.5, §16.1). Сотрудники — те же, что в mock-AD.
-- Скрипт идемпотентен: выполняется при каждом старте контейнера.
IF DB_ID(N'corp') IS NULL CREATE DATABASE corp COLLATE Cyrillic_General_CI_AS;
GO
USE corp;
GO
IF OBJECT_ID(N'dbo.employees', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.employees (
        id INT IDENTITY PRIMARY KEY,
        full_name NVARCHAR(200) NOT NULL,
        position NVARCHAR(200) NOT NULL,
        department NVARCHAR(200) NOT NULL,
        phone NVARCHAR(50) NULL,
        internal_phone NVARCHAR(10) NULL,
        email NVARCHAR(200) NULL,
        office NVARCHAR(200) NULL,
        salary DECIMAL(12, 2) NULL  -- не входит в представление: шлюз не должен его видеть
    );
    INSERT INTO dbo.employees (full_name, position, department, phone, internal_phone, email, office, salary) VALUES
    (N'Иванов Иван Петрович', N'Руководитель ИТ-отдела', N'ИТ-отдел', N'+7 (495) 100-10-01', N'1001', N'ivanov@corp.local', N'Москва, офис 1, каб. 101', 250000),
    (N'Ким Александр', N'Инженер технической поддержки', N'ИТ-отдел', N'+7 (495) 100-10-02', N'1002', N'kim@corp.local', N'Москва, офис 1, каб. 102', 150000),
    (N'Смирнова Анна Викторовна', N'Главный бухгалтер', N'Бухгалтерия', N'+7 (495) 100-20-01', N'2001', N'smirnova@corp.local', N'Москва, офис 1, каб. 214', 200000),
    (N'Петров Сергей Алексеевич', N'Бухгалтер', N'Бухгалтерия', N'+7 (495) 100-20-02', N'2002', N'petrov@corp.local', N'Москва, офис 1, каб. 215', 120000),
    (N'Петрова Ольга Игоревна', N'Менеджер по продажам', N'Отдел продаж', N'+7 (495) 100-40-07', N'4007', N'o.petrova@corp.local', N'Москва, офис 2, каб. 12', 110000),
    (N'Сидорова Елена Николаевна', N'Юрисконсульт', N'Юридический отдел', N'+7 (495) 100-30-01', N'3001', N'sidorova@corp.local', N'Москва, офис 1, каб. 301', 140000);
END
GO
CREATE OR ALTER VIEW dbo.v_phonebook AS
    SELECT full_name, position, department, phone, internal_phone, email, office FROM dbo.employees;
GO
-- Логин шлюза только на чтение: SELECT на представление, без доступа к таблице.
IF SUSER_ID(N'dg_reader') IS NULL
    EXEC (N'CREATE LOGIN dg_reader WITH PASSWORD = N''' + '$(READER_PASSWORD)' + N''', CHECK_POLICY = OFF');
GO
IF USER_ID(N'dg_reader') IS NULL CREATE USER dg_reader FOR LOGIN dg_reader;
GO
GRANT SELECT ON dbo.v_phonebook TO dg_reader;
DENY SELECT ON dbo.employees TO dg_reader;
GO

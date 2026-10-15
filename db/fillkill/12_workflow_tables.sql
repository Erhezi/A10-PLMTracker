-- Fill/Kill workflow tables: subs, orders, and the history of every change and comment.
-- Run on O2, database PLM, BEFORE deploy #2 (plan v2 §4.1). Safe to re-run.
--
--   Sub       a sub of a Medline item: vendor (name) and vendor part, Infor's vendor ID when
--             known, status, pick
--   SubOrder  an order a Materials Manager recorded against a picked sub
--   History   one row per change or comment on a sub or an order (comments live only here)
--
-- app/models/fillkill.py carries the same constraint names, so a table the app's startup
-- (db.create_all) creates matches this script. Only the defaults differ (the app always sets
-- every value); the end of this script adds any that are missing.

SET NOCOUNT ON;

IF OBJECT_ID(N'[FillKill].[Sub]', N'U') IS NULL
BEGIN
    CREATE TABLE [FillKill].[Sub] (
        [sub_id]       INT IDENTITY(1, 1) NOT NULL,
        [medline_item] VARCHAR(50)    NOT NULL,
        [vendor]       VARCHAR(255)   NOT NULL,  -- the vendor's name
        [vendor_id]    VARCHAR(20)    NULL,      -- Infor's vendor ID, when known (e.g. 1000931)
        [vendor_part]  VARCHAR(100)   NOT NULL,
        [description]  VARCHAR(255)   NULL,
        [uom]          VARCHAR(10)    NULL,
        [qoe]          DECIMAL(12, 4) NULL,
        [status]       VARCHAR(20)    NOT NULL CONSTRAINT [DF_Sub_status] DEFAULT ('pending_review'),
        [is_picked]    BIT            NOT NULL CONSTRAINT [DF_Sub_is_picked] DEFAULT (0),
        [source]       VARCHAR(20)    NOT NULL,
        [entered_by]   VARCHAR(255)   NOT NULL,
        [create_dt]    DATETIME       NOT NULL CONSTRAINT [DF_Sub_create_dt] DEFAULT (GETDATE()),
        [update_dt]    DATETIME       NOT NULL CONSTRAINT [DF_Sub_update_dt] DEFAULT (GETDATE()),
        CONSTRAINT [PK_Sub] PRIMARY KEY CLUSTERED ([sub_id]),
        CONSTRAINT [UQ_Sub_item_vendor_part] UNIQUE ([medline_item], [vendor], [vendor_part]),
        CONSTRAINT [CK_Sub_status] CHECK ([status] IN ('pending_review', 'approved', 'hold', 'rejected')),
        CONSTRAINT [CK_Sub_source] CHECK ([source] IN ('manual', 'medline_pbo', 'llm')),
        CONSTRAINT [CK_Sub_pick_needs_approved] CHECK ([is_picked] = 0 OR [status] = 'approved'),
        CONSTRAINT [CK_Sub_qoe] CHECK ([qoe] IS NULL OR [qoe] > 0)
    );
    PRINT 'Created FillKill.Sub';
END;
GO

IF OBJECT_ID(N'[FillKill].[SubOrder]', N'U') IS NULL
BEGIN
    CREATE TABLE [FillKill].[SubOrder] (
        [order_id]     INT IDENTITY(1, 1) NOT NULL,
        [sub_id]       INT            NOT NULL,
        [medline_item] VARCHAR(50)    NOT NULL,
        [quantity]     INT            NOT NULL,
        [uom]          VARCHAR(10)    NOT NULL,
        [qoe]          DECIMAL(12, 4) NULL,
        [vendor]       VARCHAR(255)   NOT NULL,
        [ordered_by]   VARCHAR(255)   NOT NULL,
        [ordered_dt]   DATETIME       NOT NULL,
        [voided_by]    VARCHAR(255)   NULL,
        [voided_at]    DATETIME       NULL,
        [void_reason]  VARCHAR(400)   NULL,
        [create_dt]    DATETIME       NOT NULL CONSTRAINT [DF_SubOrder_create_dt] DEFAULT (GETDATE()),
        [update_dt]    DATETIME       NOT NULL CONSTRAINT [DF_SubOrder_update_dt] DEFAULT (GETDATE()),
        CONSTRAINT [PK_SubOrder] PRIMARY KEY CLUSTERED ([order_id]),
        CONSTRAINT [FK_SubOrder_Sub] FOREIGN KEY ([sub_id]) REFERENCES [FillKill].[Sub] ([sub_id]),
        CONSTRAINT [CK_SubOrder_quantity] CHECK ([quantity] > 0),
        CONSTRAINT [CK_SubOrder_qoe] CHECK ([qoe] IS NULL OR [qoe] > 0),
        CONSTRAINT [CK_SubOrder_void] CHECK (
               ([voided_at] IS NULL AND [voided_by] IS NULL AND [void_reason] IS NULL)
            OR ([voided_at] IS NOT NULL AND [voided_by] IS NOT NULL AND [void_reason] IS NOT NULL)
        )
    );
    CREATE INDEX [IX_SubOrder_item_ordered] ON [FillKill].[SubOrder] ([medline_item], [ordered_dt]);
    CREATE INDEX [IX_SubOrder_sub] ON [FillKill].[SubOrder] ([sub_id]);
    PRINT 'Created FillKill.SubOrder';
END;
GO

IF OBJECT_ID(N'[FillKill].[History]', N'U') IS NULL
BEGIN
    CREATE TABLE [FillKill].[History] (
        [history_id]   BIGINT IDENTITY(1, 1) NOT NULL,
        [entity]       VARCHAR(10)    NOT NULL,
        [entity_id]    INT            NOT NULL,
        [medline_item] VARCHAR(50)    NOT NULL,
        [action]       VARCHAR(20)    NOT NULL,
        [field]        VARCHAR(30)    NULL,
        [from_value]   VARCHAR(400)   NULL,
        [to_value]     VARCHAR(400)   NULL,
        [comment]      VARCHAR(400)   NULL,
        [actor]        VARCHAR(255)   NOT NULL,
        [acted_at]     DATETIME       NOT NULL CONSTRAINT [DF_History_acted_at] DEFAULT (GETDATE()),
        CONSTRAINT [PK_History] PRIMARY KEY CLUSTERED ([history_id]),
        CONSTRAINT [CK_History_entity] CHECK ([entity] IN ('sub', 'order')),
        CONSTRAINT [CK_History_action] CHECK (
            [action] IN ('created', 'status', 'pick', 'unpick', 'comment', 'edit', 'void')
        )
    );
    CREATE INDEX [IX_History_item] ON [FillKill].[History] ([medline_item], [acted_at]);
    CREATE INDEX [IX_History_entity] ON [FillKill].[History] ([entity], [entity_id], [acted_at]);
    PRINT 'Created FillKill.History';
END;
GO

-- 2026-10-15: [vendor_id], Infor's vendor ID, when the sub has one (filled in when the Sub Finder
-- picks a contract line; optional otherwise). Medline PBO subs get Medline's (1000931) and
-- Infor's name for it, with History rows.
IF COL_LENGTH(N'FillKill.Sub', N'vendor_id') IS NULL
BEGIN
    ALTER TABLE [FillKill].[Sub] ADD [vendor_id] VARCHAR(20) NULL;
    PRINT 'Added Sub.vendor_id';
END;
GO

DECLARE @medline_vendor VARCHAR(20) = '1000931';  -- MEDLINE INDUSTRIES INC; the same in 14 (usp_SyncPboSubs)
DECLARE @medline_name VARCHAR(255) = COALESCE(
    (SELECT TOP (1) [VendorName] FROM [PLMPreprocessorShared].[infor].[MDM_VENDOR] WHERE [Vendor] = @medline_vendor),
    'MEDLINE INDUSTRIES INC');
DECLARE @moved TABLE ([sub_id] INT, [medline_item] VARCHAR(50), [old_vendor] VARCHAR(255));

BEGIN TRANSACTION;

UPDATE s SET s.[vendor_id] = @medline_vendor, s.[vendor] = @medline_name
OUTPUT inserted.[sub_id], inserted.[medline_item], deleted.[vendor] INTO @moved
FROM [FillKill].[Sub] AS s
WHERE s.[source] = 'medline_pbo' AND s.[vendor] = 'Medline' AND s.[vendor_id] IS NULL
  AND NOT EXISTS (SELECT 1 FROM [FillKill].[Sub] AS o
                  WHERE o.[medline_item] = s.[medline_item] AND o.[vendor] = @medline_name
                    AND o.[vendor_part] = s.[vendor_part]);

INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [field], [from_value],
                                  [to_value], [actor], [acted_at])
SELECT 'sub', m.[sub_id], m.[medline_item], 'edit', f.[field], f.[from_value], f.[to_value],
       '12_workflow_tables.sql', GETDATE()
FROM @moved AS m
CROSS APPLY (VALUES ('vendor', m.[old_vendor], @medline_name),
                    ('vendor_id', NULL, @medline_vendor)) AS f ([field], [from_value], [to_value]);

DECLARE @moved_count INT = (SELECT COUNT(*) FROM @moved);
PRINT CONCAT('Medline PBO subs given vendor ID ', @medline_vendor, ': ', @moved_count);

COMMIT TRANSACTION;
GO

-- Defaults, in case the app's startup created a table before this script ran.
DECLARE @defaults TABLE ([tbl] SYSNAME, [col] SYSNAME, [name] SYSNAME, [expr] NVARCHAR(100));
INSERT INTO @defaults VALUES
    (N'Sub', N'status', N'DF_Sub_status', N'(''pending_review'')'),
    (N'Sub', N'is_picked', N'DF_Sub_is_picked', N'(0)'),
    (N'Sub', N'create_dt', N'DF_Sub_create_dt', N'(GETDATE())'),
    (N'Sub', N'update_dt', N'DF_Sub_update_dt', N'(GETDATE())'),
    (N'SubOrder', N'create_dt', N'DF_SubOrder_create_dt', N'(GETDATE())'),
    (N'SubOrder', N'update_dt', N'DF_SubOrder_update_dt', N'(GETDATE())'),
    (N'History', N'acted_at', N'DF_History_acted_at', N'(GETDATE())');

DECLARE @tbl SYSNAME, @col SYSNAME, @name SYSNAME, @expr NVARCHAR(100), @sql NVARCHAR(MAX);
DECLARE d CURSOR LOCAL FAST_FORWARD FOR SELECT [tbl], [col], [name], [expr] FROM @defaults;
OPEN d;
FETCH NEXT FROM d INTO @tbl, @col, @name, @expr;
WHILE @@FETCH_STATUS = 0
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM sys.default_constraints AS dc
        JOIN sys.columns AS c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
        WHERE dc.parent_object_id = OBJECT_ID(N'[FillKill].' + QUOTENAME(@tbl)) AND c.name = @col
    )
    BEGIN
        SET @sql = N'ALTER TABLE [FillKill].' + QUOTENAME(@tbl) + N' ADD CONSTRAINT ' + QUOTENAME(@name)
                 + N' DEFAULT ' + @expr + N' FOR ' + QUOTENAME(@col) + N';';
        EXEC sp_executesql @sql;
        PRINT CONCAT('Added ', @name);
    END;
    FETCH NEXT FROM d INTO @tbl, @col, @name, @expr;
END;
CLOSE d;
DEALLOCATE d;
GO

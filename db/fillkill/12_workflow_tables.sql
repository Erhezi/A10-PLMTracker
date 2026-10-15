-- Fill/Kill workflow tables: subs, orders, and the history of every change and comment.
-- Run on O2, database PLM, BEFORE deploy #2 (plan v2 §4.1). Safe to re-run.
--
--   Sub       a sub of a Medline item: vendor (Infor's vendor ID) and its name, vendor part,
--             status, pick
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
        [vendor]       VARCHAR(255)   NOT NULL,  -- Infor's vendor ID, e.g. 1000931
        [vendor_name]  VARCHAR(255)   NULL,      -- its name in Infor's vendor master
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

-- 2026-10-15: [vendor] holds Infor's vendor ID and [vendor_name] its name. Subs made before held a
-- name in [vendor]: Medline PBO subs move to Medline's vendor ID (with a History row), and every
-- sub gets its name from Infor's vendor master, or keeps its old text as the name.
IF COL_LENGTH(N'FillKill.Sub', N'vendor_name') IS NULL
BEGIN
    ALTER TABLE [FillKill].[Sub] ADD [vendor_name] VARCHAR(255) NULL;
    PRINT 'Added Sub.vendor_name';
END;
GO

DECLARE @medline_vendor VARCHAR(20) = '1000931';  -- MEDLINE INDUSTRIES INC; the same in 14 (usp_SyncPboSubs)
DECLARE @moved TABLE ([sub_id] INT, [medline_item] VARCHAR(50));

BEGIN TRANSACTION;

UPDATE s SET s.[vendor] = @medline_vendor
OUTPUT inserted.[sub_id], inserted.[medline_item] INTO @moved
FROM [FillKill].[Sub] AS s
WHERE s.[source] = 'medline_pbo' AND s.[vendor] = 'Medline'
  AND NOT EXISTS (SELECT 1 FROM [FillKill].[Sub] AS o
                  WHERE o.[medline_item] = s.[medline_item] AND o.[vendor] = @medline_vendor
                    AND o.[vendor_part] = s.[vendor_part]);

INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [field], [from_value],
                                  [to_value], [actor], [acted_at])
SELECT 'sub', [sub_id], [medline_item], 'edit', 'vendor', 'Medline', @medline_vendor, '12_workflow_tables.sql', GETDATE()
FROM @moved;
DECLARE @moved_count INT = (SELECT COUNT(*) FROM @moved);
PRINT CONCAT('Medline PBO subs moved to vendor ID ', @medline_vendor, ': ', @moved_count);

UPDATE s SET s.[vendor_name] = COALESCE(v.[VendorName], s.[vendor])
FROM [FillKill].[Sub] AS s
LEFT JOIN [PLMPreprocessorShared].[infor].[MDM_VENDOR] AS v ON v.[Vendor] = s.[vendor]
WHERE s.[vendor_name] IS NULL;
PRINT CONCAT('Vendor names filled in: ', @@ROWCOUNT);

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

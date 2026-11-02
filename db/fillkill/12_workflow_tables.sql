-- Fill/Kill workflow tables: subs, their vendor items, orders, the history of every change and
-- comment, and SCM's instructions. Run on O2, database PLM, BEFORE deploy #2 (plan v2 §4.1),
-- and again before the coordination release (2026-10-27). Safe to re-run.
--
--   Sub            a sub of a Medline item: the Reference SKU nursing (or a Sub Finder) entered,
--                  its status, and whether it's the Approver's Pick
--   SubVendorItem  what can be ordered for a sub: a vendor's part in a UOM, with Infor's vendor ID
--                  (the Materials Manager's or a Sub Finder's); one per vendor ID, vendor part and UOM
--   SubOrder       an order a Materials Manager recorded for a vendor item of a picked sub, for a
--                  site, with Infor's PO number if they gave it; it keeps the vendor part, vendor,
--                  vendor ID, UOM and QOE it was placed with
--   History        one row per change or comment on a sub, a vendor item or an order (comments
--                  live only here)
--   ItemInstruction  an SCM instruction to the sites on how to order an item (2026-10-27),
--                  per Infor item; never changed, the newest is in force
--
-- app/models/fillkill.py carries the same constraint names, so a table the app's startup
-- (db.create_all) creates matches this script. Only the defaults differ (the app always sets
-- every value); the end of this script adds any that are missing.
--
-- What it does, in order (each step only when needed, so re-running changes nothing):
--   1. Creates Sub, SubVendorItem, SubOrder, History and ItemInstruction in their current shape.
--   2. 2026-10-20, vendor items: brings the tables O2 has had since 2026-10-20 up to date. Until then
--      a sub carried one set of vendor details (the vendor part ordered, vendor, vendor ID, UOM, QOE,
--      manufacturer part, Infor item, description). Nursing often enters the manufacturer's part,
--      which several vendors sell in several UOMs, so a sub now keeps what was entered (its
--      Reference SKU) and has a vendor item for each way to order it.
--      2a. Sub.reference_sku; SubOrder.vendor_item_id and vendor_part; CK_History_entity allows
--          'vendoritem'
--      2b. Moves the data, in one transaction, and saves a copy of Sub as it was first
--          (Sub_before_vendor_items); then Sub's vendor details are dropped
--   3. 2026-10-27, the coordination release: SubOrder.site (the Sold-To it was ordered for) and
--      SubOrder.po_number, empty on the orders recorded before.
--   4. Adds any default a table made by the app's startup lacks.
--
-- Its earlier steps 2a-2e (2026-10-15 to 10-20) brought older tables to the shape step 2 starts
-- from. O2 has had that shape since 2026-10-20, so they're gone; git history has them.
--
-- A change to what the app needs from these tables goes in step 1 (the shape) and as a new step
-- (bringing an older table up to it), and in app/fillkill/health.py and 09_verify.sql.

SET NOCOUNT ON;

-- 1. The tables --------------------------------------------------------------------------

IF OBJECT_ID(N'[FillKill].[Sub]', N'U') IS NULL
BEGIN
    CREATE TABLE [FillKill].[Sub] (
        [sub_id]        INT IDENTITY(1, 1) NOT NULL,
        [medline_item]  VARCHAR(50)    NOT NULL,
        [reference_sku] VARCHAR(100)   NOT NULL,  -- as entered: nursing's approved reference, or Medline's PBO number
        [status]        VARCHAR(20)    NOT NULL CONSTRAINT [DF_Sub_status] DEFAULT ('pending_review'),
        [is_picked]     BIT            NOT NULL CONSTRAINT [DF_Sub_is_picked] DEFAULT (0),
        [source]        VARCHAR(20)    NOT NULL,
        [entered_by]    VARCHAR(255)   NOT NULL,
        [create_dt]     DATETIME       NOT NULL CONSTRAINT [DF_Sub_create_dt] DEFAULT (GETDATE()),
        [update_dt]     DATETIME       NOT NULL CONSTRAINT [DF_Sub_update_dt] DEFAULT (GETDATE()),
        [deleted_at]    DATETIME       NULL,      -- a deleted sub keeps its row: who, when and why
        [deleted_by]    VARCHAR(255)   NULL,
        [delete_reason] VARCHAR(400)   NULL,
        CONSTRAINT [PK_Sub] PRIMARY KEY CLUSTERED ([sub_id]),
        CONSTRAINT [CK_Sub_status] CHECK ([status] IN ('pending_review', 'approved', 'hold', 'rejected')),
        CONSTRAINT [CK_Sub_source] CHECK ([source] IN ('manual', 'medline_pbo', 'llm')),
        CONSTRAINT [CK_Sub_pick_needs_approved] CHECK ([is_picked] = 0 OR [status] = 'approved'),
        CONSTRAINT [CK_Sub_delete] CHECK (
       ([deleted_at] IS NULL AND [deleted_by] IS NULL AND [delete_reason] IS NULL)
    OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL AND [delete_reason] IS NOT NULL AND [is_picked] = 0)
        )
    );
    -- One live sub per item and Reference SKU; deleted ones don't count.
    CREATE UNIQUE INDEX [UX_Sub_item_reference_sku] ON [FillKill].[Sub] ([medline_item], [reference_sku])
        WHERE [deleted_at] IS NULL;
    PRINT 'Created FillKill.Sub';
END;
GO

IF OBJECT_ID(N'[FillKill].[SubVendorItem]', N'U') IS NULL
BEGIN
    CREATE TABLE [FillKill].[SubVendorItem] (
        [vendor_item_id]    INT IDENTITY(1, 1) NOT NULL,
        [sub_id]            INT            NOT NULL,
        [vendor_part]       VARCHAR(100)   NOT NULL,  -- the vendor's part number: the one ordered
        [vendor]            VARCHAR(255)   NOT NULL,  -- the vendor's name
        [vendor_id]         VARCHAR(20)    NOT NULL,  -- Infor's vendor ID (e.g. 1000931), or 0000000: not in Infor
        [uom]               VARCHAR(10)    NOT NULL,
        [qoe]               DECIMAL(12, 4) NULL,
        [manufacturer_part] VARCHAR(100)   NULL,
        [infor_item]        VARCHAR(50)    NULL,      -- Infor's item number for it, when it has one
        [description]       VARCHAR(255)   NULL,
        [entered_by]        VARCHAR(255)   NOT NULL,
        [create_dt]         DATETIME       NOT NULL CONSTRAINT [DF_SubVendorItem_create_dt] DEFAULT (GETDATE()),
        [update_dt]         DATETIME       NOT NULL CONSTRAINT [DF_SubVendorItem_update_dt] DEFAULT (GETDATE()),
        [deleted_at]        DATETIME       NULL,      -- a deleted vendor item keeps its row and its orders
        [deleted_by]        VARCHAR(255)   NULL,
        [delete_reason]     VARCHAR(400)   NULL,
        CONSTRAINT [PK_SubVendorItem] PRIMARY KEY CLUSTERED ([vendor_item_id]),
        CONSTRAINT [FK_SubVendorItem_Sub] FOREIGN KEY ([sub_id]) REFERENCES [FillKill].[Sub] ([sub_id]),
        CONSTRAINT [CK_SubVendorItem_qoe] CHECK ([qoe] IS NULL OR [qoe] > 0),
        CONSTRAINT [CK_SubVendorItem_delete] CHECK (
               ([deleted_at] IS NULL AND [deleted_by] IS NULL AND [delete_reason] IS NULL)
            OR ([deleted_at] IS NOT NULL AND [deleted_by] IS NOT NULL AND [delete_reason] IS NOT NULL)
        )
    );
    -- One live vendor item per sub, vendor ID, vendor part and UOM.
    CREATE UNIQUE INDEX [UX_SubVendorItem_vendor_part_uom]
        ON [FillKill].[SubVendorItem] ([sub_id], [vendor_id], [vendor_part], [uom]) WHERE [deleted_at] IS NULL;
    PRINT 'Created FillKill.SubVendorItem';
END;
GO

IF OBJECT_ID(N'[FillKill].[SubOrder]', N'U') IS NULL
BEGIN
    CREATE TABLE [FillKill].[SubOrder] (
        [order_id]       INT IDENTITY(1, 1) NOT NULL,
        [sub_id]         INT            NOT NULL,
        [vendor_item_id] INT            NULL,      -- the vendor item ordered; step 2 links the older orders it can
        [medline_item]   VARCHAR(50)    NOT NULL,
        [site]           VARCHAR(20)    NULL,      -- Medline's Sold-To it was ordered for; none before 2026-10-27
        [po_number]      VARCHAR(20)    NULL,      -- Infor's PO number, when given (2026-10-27)
        [quantity]       INT            NOT NULL,
        [vendor_part]    VARCHAR(100)   NOT NULL,  -- what it was placed with, as the four below
        [uom]            VARCHAR(10)    NOT NULL,
        [qoe]            DECIMAL(12, 4) NULL,
        [vendor]         VARCHAR(255)   NOT NULL,
        [vendor_id]      VARCHAR(20)    NULL,
        [ordered_by]     VARCHAR(255)   NOT NULL,
        [ordered_dt]     DATETIME       NOT NULL,
        [voided_by]      VARCHAR(255)   NULL,
        [voided_at]      DATETIME       NULL,
        [void_reason]    VARCHAR(400)   NULL,
        [create_dt]      DATETIME       NOT NULL CONSTRAINT [DF_SubOrder_create_dt] DEFAULT (GETDATE()),
        [update_dt]      DATETIME       NOT NULL CONSTRAINT [DF_SubOrder_update_dt] DEFAULT (GETDATE()),
        CONSTRAINT [PK_SubOrder] PRIMARY KEY CLUSTERED ([order_id]),
        CONSTRAINT [FK_SubOrder_Sub] FOREIGN KEY ([sub_id]) REFERENCES [FillKill].[Sub] ([sub_id]),
        CONSTRAINT [FK_SubOrder_SubVendorItem] FOREIGN KEY ([vendor_item_id])
            REFERENCES [FillKill].[SubVendorItem] ([vendor_item_id]),
        CONSTRAINT [CK_SubOrder_quantity] CHECK ([quantity] > 0),
        CONSTRAINT [CK_SubOrder_qoe] CHECK ([qoe] IS NULL OR [qoe] > 0),
        CONSTRAINT [CK_SubOrder_void] CHECK (
               ([voided_at] IS NULL AND [voided_by] IS NULL AND [void_reason] IS NULL)
            OR ([voided_at] IS NOT NULL AND [voided_by] IS NOT NULL AND [void_reason] IS NOT NULL)
        )
    );
    CREATE INDEX [IX_SubOrder_item_ordered] ON [FillKill].[SubOrder] ([medline_item], [ordered_dt]);
    CREATE INDEX [IX_SubOrder_sub] ON [FillKill].[SubOrder] ([sub_id]);
    CREATE INDEX [IX_SubOrder_vendor_item] ON [FillKill].[SubOrder] ([vendor_item_id]);
    PRINT 'Created FillKill.SubOrder';
END;
GO

IF OBJECT_ID(N'[FillKill].[History]', N'U') IS NULL
BEGIN
    CREATE TABLE [FillKill].[History] (
        [history_id]   BIGINT IDENTITY(1, 1) NOT NULL,
        [entity]       VARCHAR(10)    NOT NULL,  -- sub, vendoritem or order
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
        CONSTRAINT [CK_History_entity] CHECK ([entity] IN ('sub', 'vendoritem', 'order')),
        CONSTRAINT [CK_History_action] CHECK (
            [action] IN ('created', 'status', 'pick', 'unpick', 'comment', 'edit', 'void', 'delete')
        )
    );
    CREATE INDEX [IX_History_item] ON [FillKill].[History] ([medline_item], [acted_at]);
    CREATE INDEX [IX_History_entity] ON [FillKill].[History] ([entity], [entity_id], [acted_at]);
    PRINT 'Created FillKill.History';
END;
GO

IF OBJECT_ID(N'[FillKill].[ItemInstruction]', N'U') IS NULL
BEGIN
    CREATE TABLE [FillKill].[ItemInstruction] (
        [instruction_id] INT IDENTITY(1, 1) NOT NULL,
        [infor_item]     VARCHAR(50)    NULL,      -- the main table's row; none for a Medline item not in Infor
        [medline_item]   VARCHAR(50)    NOT NULL,  -- the Medline item it was written from
        [instruction]    VARCHAR(1000)  NOT NULL,
        [written_by]     VARCHAR(255)   NOT NULL,
        [written_at]     DATETIME       NOT NULL CONSTRAINT [DF_ItemInstruction_written_at] DEFAULT (GETDATE()),
        CONSTRAINT [PK_ItemInstruction] PRIMARY KEY CLUSTERED ([instruction_id])
    );
    CREATE INDEX [IX_ItemInstruction_infor_item] ON [FillKill].[ItemInstruction] ([infor_item], [written_at]);
    CREATE INDEX [IX_ItemInstruction_medline_item] ON [FillKill].[ItemInstruction] ([medline_item], [written_at]);
    PRINT 'Created FillKill.ItemInstruction';
END;
GO

-- 2. 2026-10-20: vendor items -------------------------------------------------------------
-- 2a. The new columns, empty for now (only while Sub still has its vendor details), the order's
-- link to its vendor item, and History's new entity.
IF COL_LENGTH(N'FillKill.Sub', N'vendor_part') IS NOT NULL
BEGIN
    IF COL_LENGTH(N'FillKill.Sub', N'reference_sku') IS NULL
        ALTER TABLE [FillKill].[Sub] ADD [reference_sku] VARCHAR(100) NULL;
    IF COL_LENGTH(N'FillKill.SubOrder', N'vendor_part') IS NULL
        ALTER TABLE [FillKill].[SubOrder] ADD [vendor_part] VARCHAR(100) NULL;
    PRINT 'Sub.reference_sku and SubOrder.vendor_part are there, to be filled in';
END;

IF COL_LENGTH(N'FillKill.SubOrder', N'vendor_item_id') IS NULL
BEGIN
    ALTER TABLE [FillKill].[SubOrder] ADD [vendor_item_id] INT NULL;
    PRINT 'Added SubOrder.vendor_item_id';
END;
GO

-- In EXEC, so this batch compiles before the column exists (a first run checked with NOEXEC).
IF OBJECT_ID(N'[FillKill].[FK_SubOrder_SubVendorItem]', N'F') IS NULL
BEGIN
    EXEC (N'ALTER TABLE [FillKill].[SubOrder] ADD CONSTRAINT [FK_SubOrder_SubVendorItem] FOREIGN KEY ([vendor_item_id])
            REFERENCES [FillKill].[SubVendorItem] ([vendor_item_id]);');
    PRINT 'Added FK_SubOrder_SubVendorItem';
END;

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE object_id = OBJECT_ID(N'[FillKill].[SubOrder]') AND name = N'IX_SubOrder_vendor_item')
BEGIN
    EXEC (N'CREATE INDEX [IX_SubOrder_vendor_item] ON [FillKill].[SubOrder] ([vendor_item_id]);');
    PRINT 'Created IX_SubOrder_vendor_item';
END;

IF NOT EXISTS (SELECT 1 FROM sys.check_constraints
               WHERE parent_object_id = OBJECT_ID(N'[FillKill].[History]') AND name = N'CK_History_entity'
                 AND [definition] LIKE N'%''vendoritem''%')
BEGIN
    IF OBJECT_ID(N'[FillKill].[CK_History_entity]', N'C') IS NOT NULL
        EXEC (N'ALTER TABLE [FillKill].[History] DROP CONSTRAINT CK_History_entity');
    ALTER TABLE [FillKill].[History] ADD CONSTRAINT [CK_History_entity] CHECK ([entity] IN ('sub', 'vendoritem', 'order'));
    PRINT 'CK_History_entity now allows vendoritem';
END;
GO

-- 2b. The data, in one transaction (all of it, or nothing):
--   - A copy of Sub as it was: [FillKill].[Sub_before_vendor_items]. Drop it once the subs look right.
--   - Each sub's Reference SKU is what was entered (entered_part; its vendor part for a sub older
--     than that column).
--   - Each order's vendor part is the sub's when the order was recorded, from the sub's History.
--   - Subs of a Medline item with the same Reference SKU become one: the picked one, else an
--     approved, held or pending one, else the first. Before vendor items, the same part entered twice
--     was how a sub got a second vendor part (on O2: subs 10 and 11 of B-D930299Z, both 930103).
--     The others are deleted, saying so; their vendor details and orders go to the one kept, which
--     gets a comment about it.
--   - Each sub's vendor details, when they have the vendor, its vendor ID and the UOM, become a
--     vendor item (on the sub kept); the same vendor ID, vendor part and UOM only once. Its History
--     row names who filled the details in, and when.
--   - An order is linked to the vendor item with its vendor ID, vendor part and UOM, if there is one.
--     The others (placed with details the sub no longer has) keep what they were placed with.
--   - Sub's vendor details are dropped; the vendor items have them.
-- In EXEC: these columns are dropped at the end, so a later run must not compile this batch.
IF COL_LENGTH(N'FillKill.Sub', N'vendor_part') IS NOT NULL
EXEC (N'
SET XACT_ABORT ON;  -- an error rolls the transaction back instead of leaving it open

DECLARE @now DATETIME = GETDATE();
DECLARE @by VARCHAR(255) = ''12_workflow_tables.sql'';
DECLARE @merged TABLE ([sub_id] INT PRIMARY KEY, [keeper] INT NOT NULL, [medline_item] VARCHAR(50) NOT NULL,
                       [was_picked] BIT NOT NULL);
DECLARE @items TABLE ([vendor_item_id] INT NOT NULL, [sub_id] INT NOT NULL, [entered_by] VARCHAR(255) NOT NULL,
                      [create_dt] DATETIME NOT NULL);
DECLARE @detail_fields TABLE ([field] VARCHAR(30) PRIMARY KEY);
INSERT INTO @detail_fields VALUES (''vendor_part''), (''vendor''), (''vendor_id''), (''manufacturer_part''),
    (''infor_item''), (''description''), (''uom''), (''qoe'');

BEGIN TRANSACTION;

IF OBJECT_ID(N''[FillKill].[Sub_before_vendor_items]'', N''U'') IS NULL
    SELECT * INTO [FillKill].[Sub_before_vendor_items] FROM [FillKill].[Sub];

UPDATE [FillKill].[Sub]
SET [reference_sku] = COALESCE(NULLIF(LTRIM(RTRIM([entered_part])), ''''), [vendor_part])
WHERE [reference_sku] IS NULL;

UPDATE o
SET o.[vendor_part] = COALESCE(
        (SELECT TOP (1) h.[to_value] FROM [FillKill].[History] AS h
         WHERE h.[entity] = ''sub'' AND h.[entity_id] = o.[sub_id] AND h.[action] = ''edit''
           AND h.[field] = ''vendor_part'' AND h.[acted_at] <= o.[create_dt]
         ORDER BY h.[acted_at] DESC, h.[history_id] DESC),
        (SELECT TOP (1) h.[from_value] FROM [FillKill].[History] AS h
         WHERE h.[entity] = ''sub'' AND h.[entity_id] = o.[sub_id] AND h.[action] = ''edit''
           AND h.[field] = ''vendor_part'' AND h.[acted_at] > o.[create_dt]
         ORDER BY h.[acted_at], h.[history_id]),
        s.[vendor_part])
FROM [FillKill].[SubOrder] AS o
JOIN [FillKill].[Sub] AS s ON s.[sub_id] = o.[sub_id]
WHERE o.[vendor_part] IS NULL;

INSERT INTO @merged ([sub_id], [keeper], [medline_item], [was_picked])
SELECT [sub_id], [keeper], [medline_item], [is_picked]
FROM (
    SELECT [sub_id], [medline_item], [is_picked],
           FIRST_VALUE([sub_id]) OVER (
               PARTITION BY [medline_item], [reference_sku]
               ORDER BY [is_picked] DESC,
                        CASE [status] WHEN ''approved'' THEN 0 WHEN ''hold'' THEN 1 WHEN ''pending_review'' THEN 2 ELSE 3 END,
                        [sub_id]) AS [keeper]
    FROM [FillKill].[Sub]
    WHERE [deleted_at] IS NULL
) AS ranked
WHERE [sub_id] <> [keeper];

WITH details AS (
    SELECT COALESCE(m.[keeper], s.[sub_id]) AS [sub_id], s.[vendor_part], s.[vendor], s.[vendor_id], s.[uom],
           s.[qoe], s.[manufacturer_part], s.[infor_item], s.[description],
           COALESCE(who.[actor], s.[entered_by]) AS [entered_by],
           COALESCE(span.[first_at], s.[create_dt]) AS [create_dt],
           COALESCE(span.[last_at], s.[create_dt]) AS [update_dt],
           ROW_NUMBER() OVER (PARTITION BY COALESCE(m.[keeper], s.[sub_id]), s.[vendor_id], s.[vendor_part], s.[uom]
                              ORDER BY s.[sub_id]) AS [rk]
    FROM [FillKill].[Sub] AS s
    LEFT JOIN @merged AS m ON m.[sub_id] = s.[sub_id]
    OUTER APPLY (SELECT MIN(h.[acted_at]) AS [first_at], MAX(h.[acted_at]) AS [last_at]
                 FROM [FillKill].[History] AS h JOIN @detail_fields AS f ON f.[field] = h.[field]
                 WHERE h.[entity] = ''sub'' AND h.[entity_id] = s.[sub_id] AND h.[action] = ''edit'') AS span
    OUTER APPLY (SELECT TOP (1) h.[actor]
                 FROM [FillKill].[History] AS h JOIN @detail_fields AS f ON f.[field] = h.[field]
                 WHERE h.[entity] = ''sub'' AND h.[entity_id] = s.[sub_id] AND h.[action] = ''edit''
                 ORDER BY h.[acted_at] DESC, h.[history_id] DESC) AS who
    WHERE s.[vendor] IS NOT NULL AND s.[vendor_id] IS NOT NULL AND s.[uom] IS NOT NULL
)
INSERT INTO [FillKill].[SubVendorItem] ([sub_id], [vendor_part], [vendor], [vendor_id], [uom], [qoe],
                                        [manufacturer_part], [infor_item], [description], [entered_by],
                                        [create_dt], [update_dt])
OUTPUT inserted.[vendor_item_id], inserted.[sub_id], inserted.[entered_by], inserted.[create_dt] INTO @items
SELECT [sub_id], [vendor_part], [vendor], [vendor_id], [uom], [qoe], [manufacturer_part], [infor_item],
       [description], [entered_by], [create_dt], [update_dt]
FROM details
WHERE [rk] = 1;

INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [comment], [actor], [acted_at])
SELECT ''vendoritem'', i.[vendor_item_id], s.[medline_item], ''created'',
       ''From the vendor details of the sub (12_workflow_tables.sql, 2026-10-20).'', i.[entered_by], i.[create_dt]
FROM @items AS i
JOIN [FillKill].[Sub] AS s ON s.[sub_id] = i.[sub_id];

UPDATE o SET o.[sub_id] = m.[keeper]
FROM [FillKill].[SubOrder] AS o
JOIN @merged AS m ON m.[sub_id] = o.[sub_id];

UPDATE o SET o.[vendor_item_id] = v.[vendor_item_id]
FROM [FillKill].[SubOrder] AS o
JOIN [FillKill].[SubVendorItem] AS v
  ON v.[sub_id] = o.[sub_id] AND v.[vendor_id] = o.[vendor_id] AND v.[vendor_part] = o.[vendor_part]
 AND v.[uom] = o.[uom] AND v.[deleted_at] IS NULL
WHERE o.[vendor_item_id] IS NULL;

INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [comment], [actor], [acted_at])
SELECT ''sub'', [sub_id], [medline_item], ''unpick'', CONCAT(''Unpicked: merged into sub '', [keeper], ''.''), @by, @now
FROM @merged WHERE [was_picked] = 1;

INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [comment], [actor], [acted_at])
SELECT ''sub'', [sub_id], [medline_item], ''delete'',
       CONCAT(''Merged into sub '', [keeper], '': the same Reference SKU (2026-10-20).''), @by, @now
FROM @merged;

INSERT INTO [FillKill].[History] ([entity], [entity_id], [medline_item], [action], [comment], [actor], [acted_at])
SELECT ''sub'', [keeper], [medline_item], ''comment'',
       CONCAT(''Sub '', [sub_id], '', the same Reference SKU, merged into this one (2026-10-20): ''
              , ''its vendor details are a vendor item here, and its orders are here.''), @by, @now
FROM @merged;

UPDATE s
SET s.[is_picked] = 0, s.[deleted_at] = @now, s.[deleted_by] = @by,
    s.[delete_reason] = CONCAT(''Merged into sub '', m.[keeper], '': the same Reference SKU (2026-10-20).''),
    s.[update_dt] = @now
FROM [FillKill].[Sub] AS s
JOIN @merged AS m ON m.[sub_id] = s.[sub_id];

DROP INDEX UX_Sub_item_vendor_part ON [FillKill].[Sub];
ALTER TABLE [FillKill].[Sub] DROP CONSTRAINT CK_Sub_qoe;
ALTER TABLE [FillKill].[Sub] DROP COLUMN [vendor], [vendor_id], [vendor_part], [entered_part], [manufacturer_part],
                                         [infor_item], [description], [uom], [qoe];
ALTER TABLE [FillKill].[Sub] ALTER COLUMN [reference_sku] VARCHAR(100) NOT NULL;
ALTER TABLE [FillKill].[SubOrder] ALTER COLUMN [vendor_part] VARCHAR(100) NOT NULL;
CREATE UNIQUE INDEX [UX_Sub_item_reference_sku] ON [FillKill].[Sub] ([medline_item], [reference_sku])
    WHERE [deleted_at] IS NULL;

COMMIT TRANSACTION;

DECLARE @merged_count INT = (SELECT COUNT(*) FROM @merged);
DECLARE @item_count INT = (SELECT COUNT(*) FROM @items);
PRINT CONCAT(''Vendor items: '', @item_count, '' made from the subs; '', @merged_count,
             '' sub(s) merged into another with the same Reference SKU. Sub as it was: FillKill.Sub_before_vendor_items.'');
');
GO

-- 3. 2026-10-27: the site each order was placed for, and its PO number ----------------------
-- Each site orders for itself, so an order says which site it's for; the PO number is optional, kept
-- to link orders back to the killed items later. Orders recorded before have neither.
IF COL_LENGTH(N'FillKill.SubOrder', N'site') IS NULL
BEGIN
    ALTER TABLE [FillKill].[SubOrder] ADD [site] VARCHAR(20) NULL;
    PRINT 'Added SubOrder.site';
END;
IF COL_LENGTH(N'FillKill.SubOrder', N'po_number') IS NULL
BEGIN
    ALTER TABLE [FillKill].[SubOrder] ADD [po_number] VARCHAR(20) NULL;
    PRINT 'Added SubOrder.po_number';
END;
GO

-- 4. Defaults, in case the app's startup created a table before this script ran -------------
DECLARE @defaults TABLE ([tbl] SYSNAME, [col] SYSNAME, [name] SYSNAME, [expr] NVARCHAR(100));
INSERT INTO @defaults VALUES
    (N'Sub', N'status', N'DF_Sub_status', N'(''pending_review'')'),
    (N'Sub', N'is_picked', N'DF_Sub_is_picked', N'(0)'),
    (N'Sub', N'create_dt', N'DF_Sub_create_dt', N'(GETDATE())'),
    (N'Sub', N'update_dt', N'DF_Sub_update_dt', N'(GETDATE())'),
    (N'SubVendorItem', N'create_dt', N'DF_SubVendorItem_create_dt', N'(GETDATE())'),
    (N'SubVendorItem', N'update_dt', N'DF_SubVendorItem_update_dt', N'(GETDATE())'),
    (N'SubOrder', N'create_dt', N'DF_SubOrder_create_dt', N'(GETDATE())'),
    (N'SubOrder', N'update_dt', N'DF_SubOrder_update_dt', N'(GETDATE())'),
    (N'History', N'acted_at', N'DF_History_acted_at', N'(GETDATE())'),
    (N'ItemInstruction', N'written_at', N'DF_ItemInstruction_written_at', N'(GETDATE())');

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

-- Still in a transaction here? (SSMS's "SET IMPLICIT_TRANSACTIONS" option, or a BEGIN TRAN run
-- earlier in this window.) Then what this script changed isn't saved yet, and other sessions wait
-- on the tables it changed (SSMS's Object Explorer too: "Lock request time out period exceeded").
IF @@TRANCOUNT > 0
BEGIN
    DECLARE @open_transactions INT = @@TRANCOUNT;
    RAISERROR('%d transaction(s) still open in this window: the changes made in it are not saved yet, and other sessions wait on those tables. Run COMMIT to keep them (ROLLBACK undoes them).', 16, 1, @open_transactions);
END;
GO

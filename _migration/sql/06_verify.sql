/* Phase 6 - post-deployment smoke test. Run against the TARGET PLM database.
   Read-only apart from the optional batch run at the very bottom. */
USE [PLM];
GO

PRINT '=== 1. object counts (expect: 23 tables, 16 views, 11 procedures) ===';
SELECT o.type_desc, COUNT(*) AS objects
FROM sys.objects o
JOIN sys.schemas s ON o.schema_id = s.schema_id
WHERE s.name = 'PLM' AND o.is_ms_shipped = 0 AND o.parent_object_id = 0
GROUP BY o.type_desc
ORDER BY o.type_desc;
GO

PRINT '=== 2. anything that failed to compile / has an unresolved reference ===';
SELECT s.name + '.' + o.name AS module, d.referenced_database_name,
       d.referenced_schema_name, d.referenced_entity_name
FROM sys.sql_expression_dependencies d
JOIN sys.objects o ON d.referencing_id = o.object_id
JOIN sys.schemas s ON o.schema_id = s.schema_id
WHERE s.name = 'PLM'
  AND d.referenced_id IS NULL
  AND d.referenced_database_name IS NULL   -- same-db targets that do not resolve
ORDER BY 1;
PRINT '   (zero rows = every local reference resolves)';
GO

PRINT '=== 3. the 9 cross-database references all point somewhere real ===';
SELECT ref, CASE WHEN OBJECT_ID(ref) IS NULL THEN 'MISSING' ELSE 'ok' END AS status
FROM (VALUES
    ('PLMPreprocessorShared.infor.CONTRACTLINE'),
    ('PLMPreprocessorShared.infor.INVENTORY_TRANSACTION'),
    ('PLMPreprocessorShared.infor.ITEM_LOCATION'),
    ('PLMPreprocessorShared.infor.MDM_ITEM'),
    ('PLMPreprocessorShared.infor.MDM_ITEMUOM'),
    ('PLMPreprocessorShared.infor.MDM_MANUFACTURER_NAME'),
    ('PLMPreprocessorShared.infor.MDM_REQUESTER'),
    ('PLMPreprocessorShared.infor.PURCHASEORDER_LINE'),
    ('PLMPreprocessorShared.infor.REQUISITION_LINE')
) AS v(ref);
GO

PRINT '=== 4. no reference to the OLD source schema survived the remap ===';
SELECT s.name + '.' + o.name AS module
FROM sys.sql_modules m
JOIN sys.objects o ON m.object_id = o.object_id
JOIN sys.schemas s ON o.schema_id = s.schema_id
WHERE s.name = 'PLM' AND m.definition LIKE '%DM_MONTYNT%';
PRINT '   (zero rows = clean)';
GO

PRINT '=== 5. constraints carried over (expect 6 FKs, 0 untrusted) ===';
SELECT COUNT(*) AS foreign_keys,
       SUM(CASE WHEN is_not_trusted = 1 THEN 1 ELSE 0 END) AS untrusted
FROM sys.foreign_keys fk
JOIN sys.schemas s ON fk.schema_id = s.schema_id
WHERE s.name = 'PLM';
GO

PRINT '=== 6. identity seeds (compare against source before cutover) ===';
SELECT t.name AS table_name, c.name AS identity_column,
       CONVERT(bigint, IDENT_CURRENT('PLM.' + t.name)) AS current_seed
FROM sys.columns c
JOIN sys.tables t ON c.object_id = t.object_id
JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE s.name = 'PLM' AND c.is_identity = 1
ORDER BY t.name;
GO

PRINT '=== 7. run every view - any error here is a blocking defect ===';
SET NOCOUNT ON;
DECLARE @v sysname, @sql nvarchar(max), @fails int = 0;
DECLARE cur CURSOR LOCAL FAST_FORWARD FOR
    SELECT v.name FROM sys.views v
    JOIN sys.schemas s ON v.schema_id = s.schema_id
    WHERE s.name = 'PLM' ORDER BY v.name;
OPEN cur;
FETCH NEXT FROM cur INTO @v;
WHILE @@FETCH_STATUS = 0
BEGIN
    BEGIN TRY
        SET @sql = N'SELECT TOP 1 * FROM PLM.[' + @v + N']';
        EXEC sp_executesql @sql;
        PRINT '   OK    PLM.' + @v;
    END TRY
    BEGIN CATCH
        SET @fails += 1;
        PRINT '   FAIL  PLM.' + @v + '  ->  ' + ERROR_MESSAGE();
    END CATCH;
    FETCH NEXT FROM cur INTO @v;
END
CLOSE cur; DEALLOCATE cur;
PRINT '   failing views: ' + CAST(@fails AS varchar(10));
GO

/* =========================================================================
   8. FULL BATCH RUN - the real end-to-end test.
      This WRITES to the target (refreshes ItemLocations, DailyIssueOutQty,
      burn-rate tables). Target only; the source is untouched.
      Uncomment to run, then read the log below.
   ========================================================================= */
-- EXEC PLM.usp_RunPLM_Batch;
-- GO

PRINT '=== 9. batch results - all 7 steps should say Success ===';
SELECT TOP 20 pkid, process_name, exec_start, exec_end, status, duration_ms, err_msg
FROM PLM.process_log
ORDER BY pkid DESC;
GO

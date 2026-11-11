-- PLM.usp_RunPLM_Batch is the morning batch: it runs each step below in ord order, logs each to
-- PLM.process_log, and goes on past a failed step. Run on O2, database PLM.
--
--     EXEC PLM.usp_RunPLM_Batch;
--
-- Taken from O2's live definition (2026-11-10), which has the applock guard that the copy in
-- _migration/sql/05_procs.sql lacks; usp_RunPLM_ItemGroup tests that lock. Changes since:
--   2026-11-10  step 35, sp_PLM_extractDailyParLumOrderQty_FullRefresh (DailyParLumOrderQty).

CREATE OR ALTER PROCEDURE [PLM].[usp_RunPLM_Batch]
AS
BEGIN
    SET NOCOUNT ON;

    -- ---- concurrency guard: only one usp_RunPLM_Batch at a time -------------------
    DECLARE @lock_result INT,
            @lock_resource SYSNAME = N'usp_RunPLM_Batch';

    EXEC @lock_result = sp_getapplock
        @Resource    = @lock_resource,
        @LockMode    = 'Exclusive',
        @LockOwner   = 'Session',
        @LockTimeout = 0;              -- 0 = do not queue, fail now

    IF @lock_result < 0
    BEGIN
        RAISERROR(
            N'usp_RunPLM_Batch is already running on this database (sp_getapplock returned %d); this invocation exited without doing any work.',
            16, 1, @lock_result);
        RETURN;
    END;
    -- ---------------------------------------------------------------------

    BEGIN TRY

    DECLARE @processes TABLE (process_name SYSNAME, exec_sql NVARCHAR(4000), ord INT);
    INSERT INTO @processes(process_name, exec_sql, ord)
    VALUES
      (N'PLM.sp_PLM_MakeItemLocations_FullRefresh',                         N'EXEC PLM.sp_PLM_MakeItemLocations_FullRefresh;',                10),
      (N'PLM.sp_PLM_MakeItemStartEndDate_FullRefresh',                      N'EXEC PLM.sp_PLM_MakeItemStartEndDate_FullRefresh;',             20),
      (N'PLM.sp_PLM_extractDailyIssueOutQty_FullRefresh',                   N'EXEC PLM.sp_PLM_extractDailyIssueOutQty_FullRefresh;',          30),
      (N'PLM.sp_PLM_extractDailyParLumOrderQty_FullRefresh',                N'EXEC PLM.sp_PLM_extractDailyParLumOrderQty_FullRefresh;',       35),
      (N'PLM.sp_PLM_MakeItemLocationsBR_FullRefresh',                       N'EXEC PLM.sp_PLM_MakeItemLocationsBR_FullRefresh;',              40),
      (N'PLM.sp_ProcessPendingItems',                                       N'EXEC PLM.sp_ProcessPendingItems;',                              50),
      (N'PLM.sp_PLM_MakePLMItemGroupBRRolling_ItemGroup',                   N'EXEC PLM.sp_PLM_MakePLMItemGroupBRRolling_ItemGroup;',          70),
      (N'PLM.sp_PLM_MakePLMItemBRRolling_InvID_PKID',                       N'EXEC PLM.sp_PLM_MakePLMItemBRRolling_InvID_PKID;',              80);

    DECLARE @p SYSNAME, @sql NVARCHAR(4000), @start DATETIME2(3), @end DATETIME2(3);

    DECLARE cur CURSOR LOCAL FAST_FORWARD FOR
        SELECT process_name, exec_sql FROM @processes ORDER BY ord;

    OPEN cur;
    FETCH NEXT FROM cur INTO @p, @sql;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        SET @start = SYSDATETIME();

        BEGIN TRY
            EXEC sp_executesql @sql;
            SET @end = SYSDATETIME();

            INSERT INTO PLM.process_log(process_name, exec_start, exec_end, status, err_msg)
            VALUES(@p, @start, @end, 'Success', NULL);
        END TRY
        BEGIN CATCH
            SET @end = SYSDATETIME();

            INSERT INTO PLM.process_log(process_name, exec_start, exec_end, status, err_msg)
            VALUES(@p, @start, @end, 'Error', LEFT(ERROR_MESSAGE(), 4000));

            -- keep going; uncomment to fail-fast:
            -- THROW;
        END CATCH;

        FETCH NEXT FROM cur INTO @p, @sql;
    END

    CLOSE cur; DEALLOCATE cur;
    END TRY
    BEGIN CATCH
        -- Release on the way out so a failure cannot strand the lock for the rest of
        -- the session, and leave the cursor deallocated for the same reason.
        IF CURSOR_STATUS('local', 'cur') >= 0
        BEGIN
            CLOSE cur;
            DEALLOCATE cur;
        END;

        EXEC sp_releaseapplock @Resource = @lock_resource, @LockOwner = 'Session';
        THROW;
    END CATCH;

    EXEC sp_releaseapplock @Resource = @lock_resource, @LockOwner = 'Session';
END
GO

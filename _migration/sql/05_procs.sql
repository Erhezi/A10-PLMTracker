/* Generated from LIVE PRIME by _migration/generate_ddl.py.
   Do not hand-edit - regenerate instead. */
USE [PLM];
GO

CREATE OR ALTER PROCEDURE [PLM].sp_MakeCopyItemLink as

truncate table PLM.ItemLink_copy;

SET IDENTITY_INSERT PLM.ItemLink_copy ON;
INSERT INTO PLM.ItemLink_copy
([Item Group], Item, [Manufacturer Part Num], Manufacturer, [Item Description],
[Replace Item], [Replace Item Manufacturer Part Num], [Replace Item Manufacturer],
[Replace Item Item Description], Stage, [Expected Go Live Date], CreateDT, UpdateDT, PKID, copyDT)

select [Item Group], Item, [Manufacturer Part Num], Manufacturer, [Item Description],
[Replace Item], [Replace Item Manufacturer Part Num], [Replace Item Manufacturer],
[Replace Item Item Description], Stage, [Expected Go Live Date], CreateDT, UpdateDT, PKID, GETDATE() AS copyDT
from PLM.ItemLink;
SET IDENTITY_INSERT PLM.ItemLink_copy OFF;
GO

CREATE OR ALTER PROCEDURE [PLM].[sp_PLM_MakeItemLocationsBR_FullRefresh]
    @Company        varchar(10) = '3000',
    @ParLocLike     varchar(50) = 'P%',         -- for PAR
    @InvLocLike     varchar(50) = 'I%',         -- for Inventory
    @W1             int = 7,                    -- burn-rate windows (days)
    @W2             int = 35,
    @W3             int = 91,
    @W4             int = 365,
    @ReqDays        int = 91,                   -- requisition lookback for PAR
    @PODays         int = 91,                   -- PO lookback for INV
    @DoTruncate     bit = 1                     -- 1 = TRUNCATE before refill
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    BEGIN TRY
        BEGIN TRAN;

        IF @DoTruncate = 1
        BEGIN
            TRUNCATE TABLE PLM.ItemLocationsBR;   -- your materialized table
        END

        ----------------------------------------------------------------
        -- 1) PAR locations branch
        ----------------------------------------------------------------
        ;WITH base AS (
            SELECT Inventory_base_ID, LocationType, Company, [Location], Item
            FROM PLM.ItemLocations
            WHERE LocationType in ('Inventory Location', 'Par Location')
              AND Company = @Company
              AND ([Location] LIKE @ParLocLike OR [Location] LIKE @InvLocLike)
        ),
        W1_BR AS (
            SELECT Inventory_base_ID,
                   SUM(QtyInLum * 1.0) / NULLIF(@W1, 0) AS issued_qty_w1
            FROM PLM.DailyIssueOutQty
            WHERE trx_date BETWEEN dateadd(day, -@W1, z_date) and z_date
			      and existing_days >= @W1
            GROUP BY Inventory_base_ID
        ),
        W2_BR AS (
            SELECT Inventory_base_ID,
                   SUM(QtyInLum * 1.0) / NULLIF(@W2, 0) AS issued_qty_w2
            FROM PLM.DailyIssueOutQty
            WHERE trx_date BETWEEN dateadd(day, -@W2, z_date) and z_date
			      and existing_days >= @W2
            GROUP BY Inventory_base_ID
        ),
        W3_BR AS (
            SELECT Inventory_base_ID,
                   SUM(QtyInLum * 1.0) / NULLIF(@W3, 0) AS issued_qty_w3
            FROM PLM.DailyIssueOutQty
            WHERE trx_date BETWEEN dateadd(day, -@W3, z_date) and z_date
			      and existing_days >= @W3
            GROUP BY Inventory_base_ID
        ),
        W4_BR AS (
			SELECT q.Inventory_base_ID, issued_qty_w4*d as issued_qty_w4
			FROM(
				SELECT Inventory_base_ID,
					   SUM(QtyInLum * 1.0) / NULLIF(@W4, 0) AS issued_qty_w4
				FROM PLM.DailyIssueOutQty
				WHERE trx_date BETWEEN dateadd(day, -@W4, z_date) and z_date
					  --and existing_days >= @W4
				GROUP BY Inventory_base_ID) [q]
			left join (select distinct Inventory_base_ID, @W4*1.0/iif(existing_days > 365, 365, existing_days) as d from PLM.DailyIssueOutQty) [dv]
			on q.Inventory_base_ID = dv.Inventory_base_ID
        ),
        W4_TC AS (
            select c.Inventory_base_ID, iif(issued_count_w4*d < 1, 1, try_convert(int, issued_count_w4*d)) as issued_count_w4
			from(
			SELECT Inventory_base_ID, count(1) as issued_count_w4
						FROM PLM.DailyIssueOutQty
						WHERE trx_date BETWEEN dateadd(day, -@W4, z_date) and z_date
						GROUP BY Inventory_base_ID) [c]
			left join (select distinct Inventory_base_ID, @W4*1.0/iif(existing_days > 365, 365, existing_days) as d from PLM.DailyIssueOutQty) [dv]
			on c.Inventory_base_ID = dv.Inventory_base_ID
        ),
        R_Req_PO AS (
            SELECT Company, [Location], Item,
                   CAST(0 AS DECIMAL(17,4)) AS OrderQty90_EA,
				   CAST(0 AS DECIMAL(17,4)) AS ReceivedQty90_EA,
                   CAST(0 AS DECIMAL(17,4)) AS CancelQty90_EA,
				   SUM(QtyInLum * 1.0) AS ReqQty90_EA
            FROM PLM.DailyIssueOutQty
            WHERE trx_date BETWEEN TRY_CONVERT(date, GETDATE() - @ReqDays) AND TRY_CONVERT(date, GETDATE())
              AND [Location] LIKE @ParLocLike
              AND Company = @Company
            GROUP BY Company, [Location], Item

			UNION ALL

			SELECT Company, [Location], Item,
                   SUM(OrderQty_EA)    AS OrderQty90_EA,
                   SUM(ReceivedQty_EA) AS ReceivedQty90_EA,
                   SUM(CancelQty_EA)   AS CancelQty90_EA,
				   CAST(0 AS DECIMAL(17,4)) AS ReqQty90_EA
            FROM PLM.vw_90Day_PO
            WHERE [Location] <> 'Others'
                  AND Company = @Company
            GROUP BY Company, [Location], Item
        )
        INSERT INTO PLM.ItemLocationsBR (
            Inventory_base_ID, LocationType, Company, [Location], Item,
            br7, br35, br91, br365,         -- these map to @W1..@W4
            issued_count_365,                -- counts over @W4 window
            OrderQty90_EA, ReceivedQty90_EA, CancelQty90_EA, ReqQty90_EA
        )
        SELECT
            b.Inventory_base_ID, b.LocationType, b.Company, b.[Location], b.Item,
            COALESCE(w1.issued_qty_w1, COALESCE(w2.issued_qty_w2, COALESCE(w3.issued_qty_w3, COALESCE(w4.issued_qty_w4, 0)))) AS br7,
            COALESCE(w2.issued_qty_w2, COALESCE(w3.issued_qty_w3, COALESCE(w4.issued_qty_w4, 0))) AS br35,
            COALESCE(w3.issued_qty_w3, COALESCE(w4.issued_qty_w4, 0)) AS br91,
            COALESCE(w4.issued_qty_w4, 0) AS br365,
            COALESCE(tc.issued_count_w4, 0) AS issued_count_365,
            COALESCE(rqp.OrderQty90_EA,    0) AS OrderQty90_EA,
            COALESCE(rqp.ReceivedQty90_EA, 0) AS ReceivedQty90_EA,
            COALESCE(rqp.CancelQty90_EA,   0) AS CancelQty90_EA,
            COALESCE(rqp.ReqQty90_EA, 0) AS ReqQty90_EA
        FROM base b
        LEFT JOIN W1_BR w1 ON b.Inventory_base_ID = w1.Inventory_base_ID
        LEFT JOIN W2_BR w2 ON b.Inventory_base_ID = w2.Inventory_base_ID
        LEFT JOIN W3_BR w3 ON b.Inventory_base_ID = w3.Inventory_base_ID
        LEFT JOIN W4_BR w4 ON b.Inventory_base_ID = w4.Inventory_base_ID
        LEFT JOIN W4_TC tc ON b.Inventory_base_ID = tc.Inventory_base_ID
        LEFT JOIN R_Req_PO rqp ON b.Item = rqp.Item AND b.[Location] = rqp.[Location]        

        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF @@TRANCOUNT > 0 ROLLBACK TRAN;
        THROW;
    END CATCH
	PRINT 'PLM.ItemLocationsBR refreshed.'
END
GO

CREATE OR ALTER PROCEDURE [PLM].[sp_PLM_MakeItemLocations_FullRefresh]
    @Company     varchar(10) = '3000',
    @DaysBack    int         = 7,        -- in case I have updated the table and result in conflict to Ryan's update
    @LocLike1    varchar(50) = 'I%',
    @LocLike2    varchar(50) = 'P%'      -- add more patterns if needed
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    BEGIN TRY
        TRUNCATE TABLE PLM.ItemLocations;   -- requires no FK refs; fastest minimal logging
    END TRY
    BEGIN CATCH
        -- If TRUNCATE blocked (FKs), fallback to DELETE
        DELETE FROM PLM.ItemLocations;
    END CATCH;

    WITH latest AS (
        SELECT
            il.Company, il.[Location], il.LocationText, il.LocationType, il.PreferredBin,
            il.Item, il.ItemDescription, il.ItemType, il.Active, il.Discontinued,
            il.VendorItem, il.ManufacturerNumber, il.defaultBuyUOM, il.BuyUOMMultiplier, il.AutomaticPO,
            il.StockUOM, uom.UOMConversion, il.DefaultTransactionUOM, uom2.UOMConversion as TransactionUOMMultiplier,
			il.ReorderQuantityCode, il.ReorderPoint, il.MaxOrderQty, il.MinOrderQty,
            il.OnHandQty, il.AvailableQty, il.OnOrderQty, il.UnitCostInStockUOM, il.DerivedAverageCost,
            il.[report stamp], il.[create stamp],
            ROW_NUMBER() OVER (
                PARTITION BY il.company, il.[location], il.item
                ORDER BY il.[report stamp] DESC
            ) AS rkn
        FROM PLMPreprocessorShared.infor.[ITEM_LOCATION] AS il
        LEFT JOIN PLMPreprocessorShared.infor.[MDM_ITEMUOM] AS uom
               ON il.Item = uom.Item
              AND il.StockUOM = uom.UOM
		LEFT JOIN PLMPreprocessorShared.infor.[MDM_ITEMUOM] AS uom2
		       ON il.Item = uom2.Item
			   AND il.DefaultTransactionUOM = uom2.UOM
        WHERE il.LocationType IN ('Inventory Location', 'Par Location')
          AND il.[report stamp] >= DATEADD(DAY, -@DaysBack, GETDATE())
          AND il.company = @Company
          AND (il.[Location] LIKE @LocLike1 OR il.[Location] LIKE @LocLike2)
    ),
    src AS (
        SELECT
            ROW_NUMBER() OVER (ORDER BY Company, [Location], Item) AS Inventory_base_ID,
            Company, [Location], LocationText, LocationType, PreferredBin,
            Item, ItemDescription, ItemType, Active, Discontinued,
            VendorItem, ManufacturerNumber, defaultBuyUOM, BuyUOMMultiplier, AutomaticPO,
            StockUOM, UOMConversion, DefaultTransactionUOM, TransactionUOMMultiplier,
			ReorderQuantityCode, ReorderPoint, MaxOrderQty, MinOrderQty,
            OnHandQty, AvailableQty, OnOrderQty, UnitCostInStockUOM, DerivedAverageCost,
            [report stamp], [create stamp]
        FROM latest
        WHERE rkn = 1
    )
	

    INSERT INTO PLM.ItemLocations (
        Inventory_base_ID,
        Company, [Location], LocationText, LocationType, PreferredBin,
        Item, ItemDescription, ItemType, Active, Discontinued,
        VendorItem, ManufacturerNumber, defaultBuyUOM, BuyUOMMultiplier, AutomaticPO,
        StockUOM, UOMConversion, DefaultTransactionUOM, InventoryTransactionUOMMultiplier,
		ReorderQuantityCode, ReorderPoint, MaxOrderQty, MinOrderQty,
        OnHandQty, AvailableQty, OnOrderQty, UnitCostInStockUOM, DerivedAverageCost,
        [report stamp], [create stamp]
    )
    SELECT *
    FROM src;

	PRINT 'PLM.ItemLocations Refreshed.'

END
GO

CREATE OR ALTER PROCEDURE [PLM].[sp_PLM_MakeItemStartEndDate_FullRefresh]
    @Company       VARCHAR(10) = '3000',
    @LocationLike  VARCHAR(50) = 'I%',   -- wildcard for inventory location
	@ParLike       VARCHAR(50) = 'P%',   -- wildcard for par location
    @LookbackDays  INT         = 366
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    BEGIN TRY
        BEGIN TRAN;

        -- If the table is FK-referenced, TRUNCATE will fail.
        -- In that case, swap TRUNCATE for DELETE below.
        TRUNCATE TABLE PLM.ItemStartEndDate;

        ;WITH base AS (
            SELECT 
                inv.[Company],
                inv.[Location],
                inv.[Item],
                inv.AvailableQty,
                inv.[report stamp],
                MAX(inv.[create stamp]) OVER (PARTITION BY inv.Item, inv.Location) AS create_date,
                MAX(CASE WHEN inv.availableQty > 0 THEN inv.[report stamp] END)
                    OVER (PARTITION BY inv.Item, inv.Location) AS last_nonzero_stamp
            FROM PLMPreprocessorShared.infor.[ITEM_LOCATION] AS inv
            WHERE inv.LocationType in ('Inventory Location', 'Par Location')
              AND (inv.[Location] LIKE @LocationLike or inv.[Location] like @ParLike)
              AND inv.Company = @Company
              AND inv.[report stamp] >= DATEADD(DAY, -@LookbackDays, GETDATE())
        ),
        tz AS (
            SELECT 
                [Location], 
                [Item], 
                MIN([report stamp]) AS first_terminal_zero
            FROM base
            WHERE AvailableQty = 0
              AND [report stamp] > last_nonzero_stamp
            GROUP BY [Location], [Item]
        ),
        a AS (
            SELECT 
                b.[Company], 
                b.[Location], 
                b.[Item], 
                coalesce(try_convert(date, b.create_date), dateadd(day, -@LookbackDays, getdate())) as create_date,
                TRY_CONVERT(date, COALESCE(COALESCE(tz.first_terminal_zero, b.last_nonzero_stamp), GETDATE())) AS z_date
            FROM base b
            LEFT JOIN tz
              ON b.Item = tz.Item
             AND b.Location = tz.Location
        )
        INSERT INTO PLM.ItemStartEndDate
            (Inventory_base_ID, Company, Location, Item, create_date, z_date)
        SELECT DISTINCT
            il.Inventory_base_ID,
            a.Company,
            a.Location,
            a.Item,
            a.create_date  AS StartDate,
            a.z_date       AS EndDate
        FROM a
        LEFT JOIN PLM.ItemLocations AS il
          ON a.Company  = il.Company
         AND a.Location = il.Location
         AND a.Item     = il.Item
        WHERE il.Inventory_base_ID IS NOT NULL
          AND a.create_date IS NOT NULL
          AND a.z_date      IS NOT NULL;

        COMMIT TRAN;
    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRAN;
        THROW;
    END CATCH

	PRINT 'ItemStartEndDate updated.'
END
GO

CREATE OR ALTER PROCEDURE PLM.sp_PLM_MakePLMItemBRRolling_InvID_PKID
AS
BEGIN
    SET NOCOUNT ON;

    IF OBJECT_ID('tempdb..#todo') IS NOT NULL DROP TABLE #todo;
    SELECT DISTINCT Inventory_base_ID, PKID
    INTO #todo
    FROM PLM.vw_PLMZDate;

    DECLARE @Inventory_base_ID BIGINT, @PKID BIGINT, @log_id BIGINT;

    DECLARE cur CURSOR FAST_FORWARD FOR
        SELECT Inventory_base_ID, PKID
        FROM #todo;

    OPEN cur;
    FETCH NEXT FROM cur INTO @Inventory_base_ID, @PKID;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        INSERT INTO PLM.PLMItemBRRolling_Log (inventory_base_id, pkid, status)
        VALUES (@Inventory_base_ID, @PKID, 'START');
        SET @log_id = SCOPE_IDENTITY();

        BEGIN TRY
            EXEC PLM.sp_PLM_PersistItemBRRolling
                 @Inventory_base_ID = @Inventory_base_ID,
                 @PKID              = @PKID;

            UPDATE PLM.PLMItemBRRolling_Log
            SET status = 'SUCCESS',
                rows_after = (
                    SELECT COUNT(*)
                    FROM PLM.PLMItemBRRolling
                    WHERE Inventory_base_ID = @Inventory_base_ID
                      AND PKID              = @PKID
                ),
                end_ts = SYSDATETIME()
            WHERE run_id = @log_id;
        END TRY
        BEGIN CATCH
            UPDATE PLM.PLMItemBRRolling_Log
            SET status = 'ERROR',
                err_msg = CONCAT(
                    'Num:',ERROR_NUMBER(),'; Sev:',ERROR_SEVERITY(),'; State:',ERROR_STATE(),
                    '; Proc:',ISNULL(ERROR_PROCEDURE(),'N/A'),
                    '; Line:',ERROR_LINE(),'; Msg:',ERROR_MESSAGE()
                ),
                end_ts = SYSDATETIME()
            WHERE run_id = @log_id;
        END CATCH;

        FETCH NEXT FROM cur INTO @Inventory_base_ID, @PKID;
    END

    CLOSE cur;
    DEALLOCATE cur;
END
GO

CREATE OR ALTER PROCEDURE [PLM].[sp_PLM_MakePLMItemGroupBRRolling_ItemGroup]
AS
BEGIN
    SET NOCOUNT ON;

    IF OBJECT_ID('tempdb..#todo') IS NOT NULL DROP TABLE #todo;
    SELECT DISTINCT
           [Item Group] AS ItemGroup,
           [Group Locations] AS Location
    INTO #todo
    FROM PLM.vw_PLMItemGroupLocation;

    DECLARE @ItemGroup INT, @Location VARCHAR(20), @log_id BIGINT;

    DECLARE cur CURSOR FAST_FORWARD FOR
        SELECT ItemGroup, Location FROM #todo;

    OPEN cur;
    FETCH NEXT FROM cur INTO @ItemGroup, @Location;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        INSERT INTO PLM.PLMItemGroupBRRolling_Log (item_group, location, status)
        VALUES (@ItemGroup, @Location, 'START');
        SET @log_id = SCOPE_IDENTITY();

        BEGIN TRY
            EXEC PLM.sp_PLM_PersistItemGroupBRRolling
                 @ItemGroup = @ItemGroup,
                 @Location  = @Location;

            UPDATE PLM.PLMItemGroupBRRolling_Log
            SET status = 'SUCCESS',
                rows_after = (
                    SELECT COUNT(*) FROM PLM.PLMItemGroupBRRolling
                    WHERE [Item Group] = @ItemGroup AND [Location] = @Location
                ),
                end_ts = SYSDATETIME()
            WHERE run_id = @log_id;
        END TRY
        BEGIN CATCH
            UPDATE PLM.PLMItemGroupBRRolling_Log
            SET status = 'ERROR',
                err_msg = CONCAT(
                    'Num:',ERROR_NUMBER(),'; Sev:',ERROR_SEVERITY(),'; State:',ERROR_STATE(),
                    '; Proc:',ISNULL(ERROR_PROCEDURE(),'N/A'),
                    '; Line:',ERROR_LINE(),'; Msg:',ERROR_MESSAGE()
                ),
                end_ts = SYSDATETIME()
            WHERE run_id = @log_id;
        END CATCH;

        FETCH NEXT FROM cur INTO @ItemGroup, @Location;
    END

    CLOSE cur;
    DEALLOCATE cur;
END
GO

CREATE OR ALTER PROCEDURE [PLM].[sp_PLM_PersistItemBRRolling]
    @Inventory_base_ID BIGINT,
    @PKID              BIGINT
AS
	DECLARE @Inventory_base_ID_x BIGINT
	DECLARE @PKID_x BIGINT
	DECLARE @Item_x VARCHAR(10)
	DECLARE @Location_x VARCHAR(20)

	SET @Inventory_base_ID_x = @Inventory_base_ID
	SET @PKID_x = @PKID
	SET @Item_x = (SELECT Item from PLM.ItemLocations WHERE Inventory_base_ID = @Inventory_base_ID_x)
	SET @Location_x = (SELECT [Location] from PLM.ItemLocations WHERE Inventory_base_ID = @Inventory_base_ID_x);

BEGIN
    SET NOCOUNT ON;

    ;WITH Inscope AS (
        SELECT  P.*,
                T.z_date,
                IIF(BRCalcType = 'ReplaceZCDR', PLM_Zdate, z_date) AS Z_date_to_use,
                G.Side
        FROM PLM.ItemStartEndDate AS T
        JOIN PLM.vw_PLMZDate     AS P
              ON T.Inventory_base_ID = P.Inventory_base_ID
        JOIN (SELECT DISTINCT [Item Group], Item, Side FROM PLM.ItemGroup) AS G
              ON P.[Item] = G.Item AND P.[Item Group] = G.[Item Group]
        WHERE P.Inventory_base_ID = @Inventory_base_ID_x
          AND P.PKID              = @PKID_x
    ),
    History AS (
        SELECT  iout.*,
                iscope.LocationType,
                iscope.Z_date_to_use,
                iscope.BRCalcStatus,
                iscope.BRCalcType,
                iscope.Side,
                iscope.[Item Group],
                iscope.days_overlap,
                iscope.days_to_start,
                iscope.PKID
        FROM PLM.DailyIssueOutQty AS iout
        JOIN Inscope AS iscope
              ON iout.Inventory_base_ID = iscope.Inventory_base_ID
        WHERE iout.trx_date BETWEEN CAST(DATEADD(DAY, -366, GETDATE()) AS date)
                                AND iscope.Z_date_to_use
    ),
    base AS (
        SELECT  *,
                SUM(QtyInLum) OVER (PARTITION BY Inventory_base_ID, PKID ORDER BY trx_date ROWS UNBOUNDED PRECEDING) AS run_sum,
                COUNT(*)       OVER (PARTITION BY Inventory_base_ID, PKID ORDER BY trx_date ROWS UNBOUNDED PRECEDING) AS run_cnt
        FROM History
    ),
    rolled AS (
        SELECT  b.*,
                Y.rolling_sum_7                      AS rolling_sum_7,
                Y.window_cnt_7                       AS rolling_trx_cnt_7,
                rolling_per_day_7  = Y.rolling_sum_7  * 1.0 / 7,
                rolling_per_trx_7  = Y.rolling_sum_7  * 1.0 / NULLIF(Y.window_cnt_7, 0),
                rolling_per_day_60 = Y.rolling_sum_60 * 1.0 / 60,
                rolling_per_trx_60 = Y.rolling_sum_60 * 1.0 / NULLIF(Y.window_cnt_60, 0)
        FROM base AS b
        OUTER APPLY (
            SELECT TOP (1) run_sum AS run_sum_left, run_cnt AS run_cnt_left
            FROM base AS b2
            WHERE b.Inventory_base_ID = b2.Inventory_base_ID
              AND b.PKID              = b2.PKID
              AND b2.trx_date <= DATEADD(DAY, -7, b.trx_date)
            ORDER BY b2.trx_date DESC
        ) AS X
        OUTER APPLY (
            SELECT TOP (1) run_sum AS run_sum_left, run_cnt AS run_cnt_left
            FROM base AS b2
            WHERE b.Inventory_base_ID = b2.Inventory_base_ID
              AND b.PKID              = b2.PKID
              AND b2.trx_date <= DATEADD(DAY, -60, b.trx_date)
            ORDER BY b2.trx_date DESC
        ) AS XX
        CROSS APPLY (
            SELECT  rolling_sum_7  = b.run_sum - COALESCE(X.run_sum_left, 0),
                    window_cnt_7   = b.run_cnt - COALESCE(X.run_cnt_left, 0),
                    rolling_sum_60 = b.run_sum - COALESCE(XX.run_sum_left, 0),
                    window_cnt_60  = b.run_cnt - COALESCE(XX.run_cnt_left, 0)
        ) AS Y
    )
    SELECT DISTINCT
        inventory_base_ID,
        PKID,
        Company,
        Location,
        Item,
        z_date,
        existing_days,
        LocationType,
        Z_date_to_use,
        BRCalcStatus,
        BRCalcType,
        [Item Group],
        Side,
        days_overlap,
        rolling_daily_avg_7    = AVG(rolling_per_day_7)  OVER (PARTITION BY Inventory_base_ID, PKID),
        rolling_daily_median_7 = PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rolling_per_day_7)
                                 OVER (PARTITION BY Inventory_base_ID, PKID),
        rolling_daily_avg_60   = AVG(rolling_per_day_60) OVER (PARTITION BY Inventory_base_ID, PKID),
        rolling_daily_median_60= PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rolling_per_day_60)
                                 OVER (PARTITION BY Inventory_base_ID, PKID),
        create_ts = SYSDATETIME()
    INTO #final
    FROM rolled;

    IF OBJECT_ID('PLM.PLMItemBRRolling', 'U') IS NULL
    BEGIN
        SELECT * INTO PLM.PLMItemBRRolling FROM #final WHERE 1 = 2;
        CREATE UNIQUE INDEX UX_PLMItemBRRolling_Grain
            ON PLM.PLMItemBRRolling (Inventory_base_ID, PKID, Company, Location, Item, z_date);
    END

	-- we need to delete by item, location, company, since inventory_base_id here is arbitrary and changes everytime we refresh PLM.ItemLocations

    DELETE R
    FROM PLM.PLMItemBRRolling AS R
    WHERE R.Item     = @Item_x
	  AND R.Location = @Location_x
      AND R.PKID     = @PKID;

    INSERT INTO PLM.PLMItemBRRolling (
        Inventory_base_ID, PKID, Company, Location, Item, z_date, existing_days,
        LocationType, Z_date_to_use, BRCalcStatus, BRCalcType, [Item Group], Side,
        days_overlap, rolling_daily_avg_7, rolling_daily_median_7,
        rolling_daily_avg_60, rolling_daily_median_60, create_ts
    )
    SELECT
        Inventory_base_ID, PKID, Company, Location, Item, z_date, existing_days,
        LocationType, Z_date_to_use, BRCalcStatus, BRCalcType, [Item Group], Side,
        days_overlap, rolling_daily_avg_7, rolling_daily_median_7,
        rolling_daily_avg_60, rolling_daily_median_60, create_ts
    FROM #final;
END
GO

CREATE OR ALTER PROCEDURE [PLM].[sp_PLM_PersistItemGroupBRRolling]
    @ItemGroup INT,
    @Location  VARCHAR(20)   -- adjust length to your Location column size
AS

    DECLARE @ItemGroup_x INT
	DECLARE @Location_x varchar(20)

	SET @ItemGroup_x = @ItemGroup
	SET @Location_x = @Location;

BEGIN
    SET NOCOUNT ON;

    ;WITH Inscope AS (
        SELECT T.*, 
			   iif(T.[Location] like 'I%', 'Inventory Location', 'Par Location') as LocationType, 
		       G.[Item Group]
        FROM PLM.ItemStartEndDate [T]
        JOIN (SELECT distinct [Item Group], Item FROM PLM.ItemGroup) [G]
        ON T.[Item] = G.Item 
        where G.[Item Group] = @ItemGroup_x and T.[Location] = @Location_x
    ),
    History AS (
        SELECT [Item Group], [Location], Company, [LocationType], trx_date, sum(QtyInLum) as QtyInLum
        from(
              select [is].[Item Group], [is].[Location], [is].Company, [is].LocationType, iout.trx_date, iout.QtyInLum
              from Inscope [is]
              join PLM.DailyIssueOutQty [iout]
              on [is].Inventory_base_ID = iout.Inventory_base_ID)[t]
        group by [Item Group], [Location], Company, [LocationType], trx_date
    ),
    base AS (
        SELECT  *,
                SUM(QtyInLum) OVER (
                    PARTITION BY [Item Group], [Location]
                    ORDER BY trx_date
                    ROWS UNBOUNDED PRECEDING
                ) AS run_sum,
                COUNT(*) OVER (
                    PARTITION BY [Item Group], [Location]
                    ORDER BY trx_date
                    ROWS UNBOUNDED PRECEDING
                ) AS run_cnt
        FROM History
    ),
    rolled AS (
        SELECT  b.*,
                Y.rolling_sum_7    AS rolling_sum_7,
                Y.window_cnt_7     AS rolling_trx_cnt_7,
                rolling_per_day_7  = Y.rolling_sum_7  * 1.0 / 7,
                rolling_per_trx_7  = Y.rolling_sum_7  * 1.0 / NULLIF(Y.window_cnt_7, 0),
                rolling_per_day_60 = Y.rolling_sum_60 * 1.0 / 60,
                rolling_per_trx_60 = Y.rolling_sum_60 * 1.0 / NULLIF(Y.window_cnt_60, 0)
        FROM base AS b
        OUTER APPLY (
            SELECT TOP (1) run_sum AS run_sum_left, run_cnt AS run_cnt_left
            FROM base AS b2
            WHERE b.[Item Group] = b2.[Item Group]
              AND b.[Location]   = b2.[Location]
              AND b2.trx_date <= DATEADD(DAY, -7, b.trx_date)
            ORDER BY b2.trx_date DESC
        ) AS X
        OUTER APPLY (
            SELECT TOP (1) run_sum AS run_sum_left, run_cnt AS run_cnt_left
            FROM base AS b2
            WHERE b.[Item Group] = b2.[Item Group]
              AND b.[Location]   = b2.[Location]
              AND b2.trx_date <= DATEADD(DAY, -60, b.trx_date)
            ORDER BY b2.trx_date DESC
        ) AS XX
        CROSS APPLY (
            SELECT  rolling_sum_7  = b.run_sum - COALESCE(X.run_sum_left, 0),
                    window_cnt_7   = b.run_cnt - COALESCE(X.run_cnt_left, 0),
                    rolling_sum_60 = b.run_sum - COALESCE(XX.run_sum_left, 0),
                    window_cnt_60  = b.run_cnt - COALESCE(XX.run_cnt_left, 0)
        ) AS Y
    )
    SELECT DISTINCT
        [Item Group],
        [Location],
        Company,
        LocationType,
        rolling_daily_avg_7     = AVG(rolling_per_day_7)  OVER (PARTITION BY [Item Group], [Location]),
        rolling_daily_median_7  = PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rolling_per_day_7)
                                  OVER (PARTITION BY [Item Group], [Location]),
        rolling_daily_avg_60    = AVG(rolling_per_day_60) OVER (PARTITION BY [Item Group], [Location]),
        rolling_daily_median_60 = PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY rolling_per_day_60)
                                  OVER (PARTITION BY [Item Group], [Location]),
        create_ts               = SYSDATETIME()
    INTO #final
    FROM rolled;

    -- Create target table on first run (schema inferred)
    IF OBJECT_ID('PLM.PLMItemGroupBRRolling', 'U') IS NULL
    BEGIN
        SELECT * INTO PLM.PLMItemGroupBRRolling FROM #final WHERE 1=2;
        CREATE UNIQUE INDEX UX_PLMItemGroupBRRolling
            ON PLM.PLMItemGroupBRRolling ([Item Group], [Location], Company);
    END

    -- Refresh all companies for this (Item Group, Location) pair
    DELETE R
    FROM PLM.PLMItemGroupBRRolling AS R
    WHERE R.[Item Group] = @ItemGroup
      AND R.[Location]   = @Location;

    INSERT INTO PLM.PLMItemGroupBRRolling (
        [Item Group],
        [Location],
        Company,
        LocationType,
        rolling_daily_avg_7,
        rolling_daily_median_7,
        rolling_daily_avg_60,
        rolling_daily_median_60,
        create_ts
    )
    SELECT
        [Item Group],
        [Location],
        Company,
        LocationType,
        rolling_daily_avg_7,
        rolling_daily_median_7,
        rolling_daily_avg_60,
        rolling_daily_median_60,
        create_ts
    FROM #final;
END
GO

CREATE OR ALTER PROCEDURE [PLM].[sp_PLM_extractDailyIssueOutQty_FullRefresh]

	@Company        varchar(10) = '3000',
    @ParLocLike     varchar(50) = 'P%',         -- for PAR
    @InvLocLike     varchar(50) = 'I%',     -- for Inventory
	@LookBackDays   int = 366
AS
BEGIN
    SET NOCOUNT ON;
	BEGIN TRY
	-- TRUNCATE
	TRUNCATE TABLE PLM.DailyIssueOutQty;

	-- RELOAD
	;WITH a AS (
            SELECT
                Company,
                Location,
                Item,
                TRY_CONVERT(date, [create stamp]) AS trx_date,
                StockUOM,
                SUM(QtyInStockUOM) AS QtyInStockUOM
            FROM (
                SELECT
                    Company,
                    Location,
                    Item,
                    [create stamp],
                    StockUOM,
                    CAST(QtyInStockUOM * (-1.0) AS DECIMAL(18,4)) AS QtyInStockUOM
                FROM PLMPreprocessorShared.infor.[INVENTORY_TRANSACTION]
                WHERE Location LIKE @InvLocLike
                  AND Company = @Company
                  AND DocumentType = 'Inventory Issue'
                  AND [Status] = 'Released'
                  AND [create stamp] > DATEADD(DAY, -@LookBackDays, GETDATE())
            ) x
            GROUP BY Company, Item, Location, TRY_CONVERT(date, [create stamp]), StockUOM
        ),
        b AS (
            SELECT
                Company,
                [Location],
                Item,
                TRY_CONVERT(date, [create stamp]) AS trx_date,
                StockUOM,
                SUM(QtyInStockUOM) AS QtyInStockUOM
            FROM (
                SELECT
                    ToCompany AS Company,
                    [ToRequestingLocation] AS [Location],
                    Item,
                    [create stamp],
                    StockUOM,
                    CAST(QtyInStockUOM * (-1.0) AS DECIMAL(18,4)) AS QtyInStockUOM
                FROM PLMPreprocessorShared.infor.[INVENTORY_TRANSACTION]
                WHERE [ToRequestingLocation] LIKE @ParLocLike
                  AND ToCompany = @Company
                  AND DocumentType = 'Inventory Issue'
                  AND [Status] = 'Released'
                  AND [create stamp] > DATEADD(DAY, -@LookBackDays, GETDATE())
            ) y
            GROUP BY Company, [Location], Item, TRY_CONVERT(date, [create stamp]), StockUOM
        ),
        uab AS (
            SELECT * FROM a
            UNION ALL
            SELECT * FROM b
        ),
		u AS (
		SELECT Company, [Location], Item, trx_date, UOM as LUM, SUM(QtyInStockUOM * UOMConversion) as QtyInLum
		FROM(
		SELECT uab.*, iuom.UOMConversion, lowest_uom.UOM
		FROM uab
		LEFT JOIN PLMPreprocessorShared.infor.[MDM_ITEMUOM] [iuom]
		ON uab.Item = iuom.Item
		and uab.StockUOM = iuom.UOM
		LEFT JOIN 
		(Select Item, UOM
		 FROM(
				SELECT Item, UOM, UOMConversion, row_number() over (partition by Item 
				order by UOMConversion, 
				CASE UOM when 'EA' THEN 1
						 when 'PR' Then 2
						 else 3 end) as rk
				FROM PLMPreprocessorShared.infor.[MDM_ITEMUOM]
				where TrackedIn = 'Yes') [lum]
		 where rk = 1
		) [lowest_uom]
		on uab.Item = lowest_uom.Item
		) [tmp]
		group by Company, [Location], Item, trx_date, UOM
		),
        iout AS (
            SELECT
                az.Inventory_base_ID,
                u.Company,
                u.Location,
                u.Item,
                u.trx_date,
                u.LUM,
                u.QtyInLum,
                az.create_date,
                az.z_date,
                DATEDIFF(DAY, az.create_date, az.z_date) AS existing_days
            FROM u
            INNER JOIN PLM.ItemStartEndDate AS az
                ON u.Item = az.Item
               AND u.Location = az.Location
               AND u.Company = az.Company
        )
        INSERT INTO PLM.DailyIssueOutQty
        (
            Inventory_base_ID,
            Company,
            Location,
            Item,
			Lum,
            trx_date,
            QtyInLum,
            create_date,
            z_date,
            existing_days
        )
        SELECT
            Inventory_base_ID,
            Company,
            Location,
            Item,
			LUM,
            trx_date,
            QtyInLum,
            create_date,
            z_date,
            existing_days
        FROM iout;

    END TRY
    BEGIN CATCH
        DECLARE @msg NVARCHAR(4000) = ERROR_MESSAGE();
        RAISERROR('sp_PLM_extractDailyIssueOutQty failed: %s', 16, 1, @msg);
        RETURN;
    END CATCH

	PRINT 'DailyIssueOutQty updated.'
END;
GO

CREATE OR ALTER PROCEDURE [PLM].[sp_ProcessPendingItems]
AS
BEGIN
    SET NOCOUNT ON;
    SET XACT_ABORT ON;

    DECLARE @applock INT;

    BEGIN TRY
        BEGIN TRANSACTION;

        EXEC @applock = sys.sp_getapplock
             @Resource    = N'PLM.sp_ProcessPendingItems',
             @LockMode    = 'Exclusive',
             @LockOwner   = 'Transaction',
             @LockTimeout = 10000;

        IF @applock < 0
        BEGIN
            ;THROW 50001,
                'sp_ProcessPendingItems could not acquire the application lock.',
                1;
        END;


        ----------------------------------------------------------------------
        -- Phase 1: collect item number from contract view & update PI/ItemLink
        ----------------------------------------------------------------------

        -- Stage candidate rows (skip locked to avoid deadlocks)
        IF OBJECT_ID('tempdb..#to_update') IS NOT NULL DROP TABLE #to_update;
        CREATE TABLE #to_update
        (
            pending_pkid  BIGINT PRIMARY KEY,
            item_link_id  BIGINT NOT NULL,
            matched_item  NVARCHAR(10) NOT NULL
        );

        INSERT INTO #to_update (pending_pkid, item_link_id, matched_item)
        SELECT DISTINCT
               p.PKID,
               p.item_link_id,
               CAST(ci.[Item] AS NVARCHAR(10)) AS matched_item
        FROM PLM.PendingItems AS p WITH (READPAST, ROWLOCK)
        INNER JOIN PLM.vw_ContractItem AS ci
            ON ci.contract_id  = p.contract_id
           AND ci.mfg_part_num = p.mfg_part_num
        WHERE UPPER(ISNULL(ci.item_type,'')) = 'ITEMMAST'
          AND UPPER(ISNULL(p.status,''))     = 'PENDING';

        IF NOT EXISTS (SELECT 1 FROM #to_update)
        BEGIN
            COMMIT TRANSACTION;
            RETURN;
        END

        -- Capture PendingItems update results for downstream work
        DECLARE @UpdatedPending TABLE
        (
            PKID BIGINT,
            item_link_id BIGINT,
            replace_item_immast VARCHAR(50),
            old_status VARCHAR(20)
        );

        -- Update PendingItems by PK (serialized)
        UPDATE p WITH (ROWLOCK, UPDLOCK, HOLDLOCK)
        SET
            p.replace_item_immast = tu.matched_item,
            p.status              = 'IMMAST',
            p.update_dt           = GETDATE()
        OUTPUT
            inserted.PKID,
            inserted.item_link_id,
            inserted.replace_item_immast,
            deleted.status
        INTO @UpdatedPending
        FROM PLM.PendingItems AS p
        INNER JOIN #to_update AS tu
            ON tu.pending_pkid = p.PKID;

        -- Capture ItemLink update results
        DECLARE @UpdatedItemLink TABLE
        (
            PKID BIGINT,
            Item NVARCHAR(50),
            ReplaceItem VARCHAR(250),
            Stage VARCHAR(100),
            UpdateDT DATETIME
        );

        UPDATE il WITH (ROWLOCK, UPDLOCK, HOLDLOCK)
        SET
            il.[Replace Item] = up.replace_item_immast,
            il.[Stage] = CASE
                            WHEN il.[Stage] = 'Pending Item Number' THEN 'Pending Clinical Readiness'
                            ELSE il.[Stage]
                         END,
            il.UpdateDT = GETDATE()
        OUTPUT
            inserted.PKID,
            inserted.[Item],
            inserted.[Replace Item],
            inserted.[Stage],
            inserted.UpdateDT
        INTO @UpdatedItemLink
        FROM PLM.ItemLink AS il
        INNER JOIN @UpdatedPending AS up
            ON up.item_link_id = il.PKID
        WHERE up.replace_item_immast IS NOT NULL;

        ----------------------------------------------------------------------
        -- Phase 2: upsert ItemGroup one-by-one; log failures; collect PKIDs
        ----------------------------------------------------------------------

        -- Prepare membership seed (derive [Item Group] at time of use)
        IF OBJECT_ID('tempdb..#seed') IS NOT NULL DROP TABLE #seed;
        CREATE TABLE #seed
        (
            row_id INT IDENTITY(1,1) PRIMARY KEY,
            pending_pkid BIGINT NOT NULL,
            item_link_id BIGINT NOT NULL,
            item NVARCHAR(10) NOT NULL,
            [Item Group] INT NOT NULL,
            side CHAR(1) NOT NULL DEFAULT('R')
        );

        INSERT INTO #seed (pending_pkid, item_link_id, item, [Item Group], side)
        SELECT DISTINCT
            up.PKID,
            up.item_link_id,
            CAST(up.replace_item_immast AS NVARCHAR(10)) AS item,
            il.[Item Group],
            'R'
        FROM @UpdatedPending up
        INNER JOIN PLM.ItemLink il
            ON il.PKID = up.item_link_id
        WHERE up.replace_item_immast IS NOT NULL;

        -- Will track successful (item_group_pkid, item_link_id) pairs for Phase 3
        DECLARE @ResolvedLinks TABLE
        (
            item_group_pkid BIGINT,
            item_link_id BIGINT,
            pending_pkid BIGINT
        );

        DECLARE @cur INT = 1, @max INT = (SELECT COUNT(*) FROM #seed);

        WHILE @cur <= @max
        BEGIN
            DECLARE
                @pending_pkid BIGINT,
                @item_link_id BIGINT,
                @item NVARCHAR(10),
                @group INT,
                @side CHAR(1),
                @item_group_pkid BIGINT;

            SELECT
                @pending_pkid = s.pending_pkid,
                @item_link_id = s.item_link_id,
                @item         = s.item,
                @group        = s.[Item Group],
                @side         = s.side
            FROM #seed s WHERE s.row_id = @cur;

            BEGIN TRY
                -- Try to find existing membership, serialize on key
                SELECT @item_group_pkid = g.PKID
                FROM PLM.ItemGroup g WITH (UPDLOCK, HOLDLOCK, ROWLOCK)
                WHERE g.Item = @item
                  AND g.[Item Group] = @group
                  AND g.Side = @side;

                IF @item_group_pkid IS NOT NULL
                BEGIN
                    -- Touch update_dt
                    UPDATE PLM.ItemGroup WITH (ROWLOCK, UPDLOCK, HOLDLOCK)
                    SET update_dt = GETDATE()
                    WHERE PKID = @item_group_pkid;
                END
                ELSE
                BEGIN
                    -- Insert new membership (unique on Item,Group,Side)
                    INSERT INTO PLM.ItemGroup (Item, [Item Group], Side, create_dt, update_dt)
                    VALUES (@item, @group, @side, GETDATE(), GETDATE());
                    SET @item_group_pkid = SCOPE_IDENTITY();
                END

                -- Record success to drive Phase 3
                INSERT INTO @ResolvedLinks (item_group_pkid, item_link_id, pending_pkid)
                VALUES (@item_group_pkid, @item_link_id, @pending_pkid);
            END TRY
            BEGIN CATCH
                DECLARE @ErrMsg NVARCHAR(4000) = ERROR_MESSAGE();
                -- Log the failure; do NOT abort the batch
                INSERT INTO PLM.ConflictErrorPendingItemAddition_log
                    (item_link_id, pending_pkid, item, [Item Group], side, create_dt, error_msg)
                VALUES
                    (@item_link_id, @pending_pkid, @item, @group, @side, GETDATE(), @ErrMsg);

                -- If it was a unique key race, try to recover PKID so Phase 3 can proceed
                IF ERROR_NUMBER() IN (2601, 2627)
                BEGIN
                    SELECT @item_group_pkid = g.PKID
                    FROM PLM.ItemGroup g WITH (UPDLOCK, HOLDLOCK)
                    WHERE g.Item = @item AND g.[Item Group] = @group AND g.Side = @side;

                    IF @item_group_pkid IS NOT NULL
                    BEGIN
                        INSERT INTO @ResolvedLinks (item_group_pkid, item_link_id, pending_pkid)
                        VALUES (@item_group_pkid, @item_link_id, @pending_pkid);
                    END
                END
                -- Clear error and continue
                -- (no THROW here—continue to next row)
            END CATCH

            SET @cur += 1;
        END

        ----------------------------------------------------------------------
        -- Phase 3: write ItemGroupLink (provenance) for successful rows
        ----------------------------------------------------------------------
        INSERT INTO PLM.ItemGroupLink (item_group_pkid, item_link_id, create_dt)
        SELECT DISTINCT
            rl.item_group_pkid,
            rl.item_link_id,
            GETDATE()
        FROM @ResolvedLinks rl
        WHERE NOT EXISTS
        (
            SELECT 1
            FROM PLM.ItemGroupLink l WITH (UPDLOCK, HOLDLOCK)
            WHERE l.item_group_pkid = rl.item_group_pkid
              AND l.item_link_id    = rl.item_link_id
        );

        COMMIT TRANSACTION;

        --------------------------------------------------------------
        -- Returns (for review/ops)
        --------------------------------------------------------------
        SELECT
            p.PKID AS Pending_PKID,
            p.item_link_id,
            p.replace_item_immast,
            p.old_status AS previous_status
        FROM @UpdatedPending p;

        SELECT
            il.PKID AS ItemLink_PKID,
            il.Item,
            il.ReplaceItem,
            il.Stage,
            il.UpdateDT
        FROM @UpdatedItemLink il;

        SELECT
            rl.pending_pkid,
            rl.item_link_id,
            rl.item_group_pkid
        FROM @ResolvedLinks rl;

    END TRY
    BEGIN CATCH
        IF XACT_STATE() <> 0 ROLLBACK TRANSACTION;

        THROW;
    END CATCH;
END
GO

CREATE OR ALTER PROCEDURE [PLM].[usp_RunPLM_Batch]
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE @processes TABLE (process_name SYSNAME, exec_sql NVARCHAR(4000), ord INT);
    INSERT INTO @processes(process_name, exec_sql, ord)
    VALUES
      (N'PLM.sp_PLM_MakeItemLocations_FullRefresh',                         N'EXEC PLM.sp_PLM_MakeItemLocations_FullRefresh;',                10),
      (N'PLM.sp_PLM_MakeItemStartEndDate_FullRefresh',                      N'EXEC PLM.sp_PLM_MakeItemStartEndDate_FullRefresh;',             20),
      (N'PLM.sp_PLM_extractDailyIssueOutQty_FullRefresh',                   N'EXEC PLM.sp_PLM_extractDailyIssueOutQty_FullRefresh;',          30),
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
END
GO


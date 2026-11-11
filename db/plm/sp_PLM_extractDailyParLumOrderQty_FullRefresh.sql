-- PLM.sp_PLM_extractDailyParLumOrderQty_FullRefresh empties PLM.DailyParLumOrderQty and refills it
-- with the purchase order lines released in the past @LookBackDays for par locations (@ParLocLike)
-- in @Company, inventoried and non-stock items: the quantity (ordered less cancelled) in the item's
-- lowest unit of measure (Lum), summed per par location, item and release date (trx_date). It is
-- step 35 of usp_RunPLM_Batch (see usp_RunPLM_Batch.sql), after ItemLocations (10) and
-- ItemStartEndDate (20), whose Inventory_base_ID and dates it takes: both are rebuilt, and the IDs
-- renumbered, each batch. Run on O2, database PLM. Safe to re-run.
--
--     EXEC PLM.sp_PLM_extractDailyParLumOrderQty_FullRefresh;
--
-- An item can be ordered for a par it is not registered at: it is kept, with Inventory_base_ID,
-- create_date, z_date and existing_days NULL.
--
-- Little data until Medline's direct LUM orders go live; from then on these are the pars' direct
-- orders, for demand forecasting.

-- 2026-11-10: the table was first made by SELECT INTO, without a key. It holds only what the
-- procedure rebuilds, so it is dropped and made again with one.
IF OBJECT_ID(N'PLM.DailyParLumOrderQty', N'U') IS NOT NULL
   AND OBJECT_ID(N'PLM.PK_DailyParLumOrderQty', N'PK') IS NULL
    DROP TABLE [PLM].[DailyParLumOrderQty];

IF OBJECT_ID(N'PLM.DailyParLumOrderQty', N'U') IS NULL
BEGIN
    CREATE TABLE [PLM].[DailyParLumOrderQty] (
        [Inventory_base_ID] bigint NULL,
        [Company] varchar(10) NOT NULL,
        [Location] varchar(20) NOT NULL,
        [Item] varchar(100) NOT NULL,
        [Lum] varchar(10) NULL,
        [trx_date] date NOT NULL,
        [QtyInLum] decimal(18,4) NULL,
        [create_date] date NULL,
        [z_date] date NULL,
        [existing_days] int NULL,
        CONSTRAINT [PK_DailyParLumOrderQty] PRIMARY KEY CLUSTERED ([Company], [Location], [Item], [trx_date])
    );
END;
GO

CREATE OR ALTER PROCEDURE [PLM].[sp_PLM_extractDailyParLumOrderQty_FullRefresh]
    @Company        varchar(10) = '3000',
    @ParLocLike     varchar(50) = 'P%',     -- par locations: PWLR%, PMOS%, PWAK%, ...
    @LookBackDays   int = 366
AS
BEGIN
    SET NOCOUNT ON;
    BEGIN TRY
    -- TRUNCATE
    TRUNCATE TABLE PLM.DailyParLumOrderQty;

    -- RELOAD
    ;WITH a AS (
            SELECT Inventory_base_ID, Company, [Location], Item
            FROM PLM.ItemLocations
            WHERE LocationType = 'Par Location'
        ),
        lum AS (
            SELECT Item, UOM
            FROM (
                SELECT Item, UOM, UOMConversion,
                       ROW_NUMBER() OVER (PARTITION BY Item
                                          ORDER BY UOMConversion,
                                                   CASE UOM WHEN 'EA' THEN 1
                                                            WHEN 'PR' THEN 2
                                                            ELSE 3 END) AS rk
                FROM PLMPreprocessorShared.infor.[MDM_ITEMUOM]
                WHERE TrackedIn = 'Yes'
            ) [lum]
            WHERE rk = 1
        ),
        b AS (
            SELECT
                po.Company,
                po.RequisitionRequestingLocation AS [Location],
                po.Item,
                po.POReleaseDate AS trx_date,
                lum.UOM AS Lum,
                (po.Quantity - po.CancelQuantity) * COALESCE(iuom.UOMConversion, po.EnteredBuyUOMMultiplier) AS QtyInLum
            FROM PLMPreprocessorShared.infor.PURCHASEORDER_LINE AS po
            LEFT JOIN PLMPreprocessorShared.infor.[MDM_ITEMUOM] AS iuom
                ON po.Item = iuom.Item
               AND po.EnteredBuyUOM = iuom.UOM
            LEFT JOIN lum
                ON po.Item = lum.Item
            WHERE po.POReleaseDate > DATEADD(DAY, -@LookBackDays, GETDATE())
              AND po.Company = @Company
              AND po.RequisitionRequestingLocation LIKE @ParLocLike
              AND po.ItemType IN ('Inventoried', 'Non Stock')
              AND po.exc_flag = 'Default'
              AND po.Item IS NOT NULL
        ),
        d AS (
            -- one row per par location, item and day (an item has one Lum)
            SELECT Company, [Location], Item, trx_date, Lum, SUM(QtyInLum) AS QtyInLum
            FROM b
            GROUP BY Company, [Location], Item, trx_date, Lum
        )
        INSERT INTO PLM.DailyParLumOrderQty
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
            a.Inventory_base_ID,
            d.Company,
            d.[Location],
            d.Item,
            d.Lum,
            d.trx_date,
            d.QtyInLum,
            zdate.create_date,
            zdate.z_date,
            DATEDIFF(DAY, zdate.create_date, zdate.z_date) AS existing_days
        FROM d
        LEFT JOIN a
            ON d.Company = a.Company
           AND d.[Location] = a.[Location]
           AND d.Item = a.Item
        LEFT JOIN PLM.ItemStartEndDate AS zdate
            ON a.Inventory_base_ID = zdate.Inventory_base_ID;

    END TRY
    BEGIN CATCH
        DECLARE @msg NVARCHAR(4000) = ERROR_MESSAGE();
        RAISERROR('sp_PLM_extractDailyParLumOrderQty failed: %s', 16, 1, @msg);
        RETURN;
    END CATCH

    PRINT 'DailyParLumOrderQty updated.'
END;
GO

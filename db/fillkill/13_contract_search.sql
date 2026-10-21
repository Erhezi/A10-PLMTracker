-- Contract-line search for "Add sub": Infor contract lines active today, with what a sub needs;
-- Infor's vendors (vw_Vendor), to check a sub's vendor ID and fill in its name; and Infor's UOM
-- for one typed another way (vw_UomAlias, 2026-10-20).
-- Run on O2, database PLM, BEFORE deploy #2 (plan v2 §4.2). Safe to re-run.
--
-- The app matches the stripped vendor item or manufacturer number first, then description words,
-- and picking a row fills vendor, vendor part, description, UOM and QOE. Measured on 2026-10-13:
-- 632k lines, 50-200 ms per search. Several words with a number among them ("930103 chloraprep",
-- 2026-10-19) search by the number, then keep the lines where every word is found.
--
-- Each result also shows the vendor ID, the Infor item number (6 digits, item-master lines only;
-- "Special" lines have numbers like 1296-DYNJAA04), and whether the line is on an MHS contract
-- ([is_mhs], 2026-10-15). Non-MHS lines can still be chosen.

SET NOCOUNT ON;
GO

CREATE OR ALTER VIEW [FillKill].[vw_ContractLineSearch] AS
SELECT cl.[Vendor]                            AS [vendor_id],
       cl.[VendorName]                        AS [vendor_name],
       cl.[VendorItem]                        AS [vendor_item],
       cl.[DerivedStrippedVendorItem]         AS [vendor_item_stripped],
       cl.[ManufacturerNumber]                AS [manufacturer_number],
       cl.[DerivedStrippedManufacturerNumber] AS [manufacturer_number_stripped],
       CAST(LEFT(cl.[ItemDescription], 255) AS VARCHAR(255)) AS [description],
       cl.[UOM]                               AS [uom],
       cl.[DerivedUOMConversion]              AS [qoe],
       cl.[ItemNumber]                        AS [infor_item],
       cl.[ItemType]                          AS [item_type],
       cl.[Contract]                          AS [contract],
       cl.[ContractName]                      AS [contract_name],
       cl.[BaseCost]                          AS [base_cost],
       iif(cl.[Contract.MMAHSOrganizationEID] = '105188574', 'Yes', 'No') AS [is_mhs]
FROM [PLMPreprocessorShared].[infor].[CONTRACTLINE] AS cl
WHERE cl.[Contract.ContractStatus] = 'Active'
  AND cl.[ContractLineState] = 'Active'
  AND cl.[ActiveLine] = 'Yes'
  AND cl.[OnHold] = 'No'
  AND cl.[Contract.OnHold] = 'No'
  AND CAST(GETDATE() AS DATE) BETWEEN cl.[EffectiveDate] AND cl.[ExpirationDate];
GO

-- Infor's vendors (2026-10-15). A sub carries Infor's vendor ID (or 0000000, "Vendor not available
-- in system"): the app checks a typed ID here and fills in the vendor's name, and a typed name is
-- looked up in all three of Infor's names (2026-10-19: legal_name and search_name added), so the
-- Materials Manager can find the ID. About 39k vendors, 10k active.
CREATE OR ALTER VIEW [FillKill].[vw_Vendor] AS
SELECT v.[Vendor]           AS [vendor_id],
       v.[VendorName]       AS [vendor_name],
       v.[LegalName]        AS [legal_name],
       v.[VendorSearchName] AS [search_name],
       v.[VendorStatus]     AS [vendor_status]
FROM [PLMPreprocessorShared].[infor].[MDM_VENDOR] AS v;
GO

-- Infor's (Lawson's) UOM for one typed another way (2026-10-20): CS is CA, VL is VI. A UOM typed
-- into a vendor item or an order correction is saved as Infor's when it's one of these external
-- values, and as typed otherwise; the order form also compares Medline's UOM to the vendor item's
-- through it. 32 rows on 10/20, all in EDI list L1_I_UOM.
CREATE OR ALTER VIEW [FillKill].[vw_UomAlias] AS
SELECT DISTINCT UPPER(LTRIM(RTRIM(u.[ExternalValue]))) AS [external_value],
                UPPER(LTRIM(RTRIM(u.[LawsonValue])))   AS [lawson_value]
FROM [PLMPreprocessorShared].[infor].[MDM_EDI_SUB_UOM] AS u;
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

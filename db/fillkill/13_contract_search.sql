-- Contract-line search for "Add sub": Infor contract lines active today, with what a sub needs;
-- and Infor's vendors (vw_Vendor), for a sub's vendor ID and name.
-- Run on O2, database PLM, BEFORE deploy #2 (plan v2 §4.2). Safe to re-run.
--
-- The app matches the stripped vendor item or manufacturer number first, then description words,
-- and picking a row fills vendor, vendor part, description, UOM and QOE. Measured on 2026-10-13:
-- 632k lines, 50-200 ms per search.
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

-- Infor's vendors (2026-10-15). A sub's vendor is Infor's vendor ID; the app reads its name here,
-- both to show it as the Sub Finder types the ID and to store it with the sub.
CREATE OR ALTER VIEW [FillKill].[vw_Vendor] AS
SELECT v.[Vendor]       AS [vendor_id],
       v.[VendorName]   AS [vendor_name],
       v.[VendorStatus] AS [vendor_status]
FROM [PLMPreprocessorShared].[infor].[MDM_VENDOR] AS v;
GO

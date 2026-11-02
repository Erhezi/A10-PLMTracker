-- Fill/Kill sites (2026-10-30): the Medline Sold-To accounts Fill/Kill deals with, each binned into
-- its campus ([site_short_name]: Moses, Wakefield or Einstein). Run on O2, database PLM. Safe to
-- re-run: it adds a site that's missing and brings a changed name or campus up to date. It never
-- removes one; delete the row by hand to drop a site.
--
-- A site is a Medline Sold-To account (MONTEFIORE-WAKEFIELD (LUM), its EVS and LAB accounts...), not
-- a Ship-To (a unit under it: 4E, ICU, ED). [sold_to] is Medline's code with its leading zeros, the
-- same value as vw_MedlineFillKill's [Sold-To] and SubOrder.site.
--
-- The app doesn't read it yet: the site filter still lists the Sold-To names in Medline's lines.

SET NOCOUNT ON;

IF OBJECT_ID(N'[FillKill].[Site]', N'U') IS NULL
BEGIN
    CREATE TABLE [FillKill].[Site] (
        [sold_to]         VARCHAR(20)    NOT NULL,  -- Medline's Sold-To code
        [sold_to_name]    VARCHAR(100)   NOT NULL,  -- Medline's Sold-To Name
        [site_short_name] VARCHAR(20)    NOT NULL,  -- the campus: Moses, Wakefield or Einstein
        CONSTRAINT [PK_Site] PRIMARY KEY CLUSTERED ([sold_to])
    );
    PRINT 'Created FillKill.Site';
END;
GO

MERGE [FillKill].[Site] AS t
USING (VALUES
    ('0002159659', 'MONTEFIORE-MOSES (LUM)',        'Moses'),
    ('0002205967', 'MONTEFIORE MOSES CAMPUS-EVS',   'Moses'),
    ('0002159655', 'MONTEFIORE-WAKEFIELD (LUM)',    'Wakefield'),
    ('0002159656', 'MONTEFIORE-WAKEFIELD (BULK)',   'Wakefield'),
    ('0002205969', 'MONTEFIORE WAKEFIELD-EVS',      'Wakefield'),
    ('0002426501', 'MONTEFIORE HL LAB - WAKEFIELD', 'Wakefield'),
    ('0002522116', 'MONTEFIORE WAKEFIELD LAB',      'Wakefield'),
    ('0002159661', 'MONTEFIORE-EINSTEIN (LUM)',     'Einstein'),
    ('0002205996', 'MONTEFIORE EINSTEIN-EVS',       'Einstein'),
    ('0002496504', 'MONTEFIORE-EINSTEIN LAB',       'Einstein')
) AS s ([sold_to], [sold_to_name], [site_short_name])
ON t.[sold_to] = s.[sold_to]
WHEN MATCHED AND (t.[sold_to_name] <> s.[sold_to_name] OR t.[site_short_name] <> s.[site_short_name]) THEN
    UPDATE SET [sold_to_name] = s.[sold_to_name], [site_short_name] = s.[site_short_name]
WHEN NOT MATCHED BY TARGET THEN
    INSERT ([sold_to], [sold_to_name], [site_short_name])
    VALUES (s.[sold_to], s.[sold_to_name], s.[site_short_name]);
PRINT CONCAT(@@ROWCOUNT, ' site(s) added or changed');
GO

SELECT [site_short_name], [sold_to], [sold_to_name]
FROM [FillKill].[Site]
ORDER BY [site_short_name], [sold_to];
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

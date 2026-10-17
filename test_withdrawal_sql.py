
import app as portal

TEST_MOBILE = "0000000000"

conn = portal.get_db()
cur = conn.cursor()

try:
    # Begin a transaction. All test changes will be rolled back.
    cur.execute("SAVEPOINT withdrawal_test")

    # Create two temporary pending applications.
    cur.execute(
        """
        INSERT INTO applications (
            application_no, applicant_name, mobile, dob,
            village, block, bank_account, ifsc, doc_path,
            status, submitted_at
        )
        VALUES
            ('TEST-WD-001', 'Withdrawal Test', %s, '1950-01-01',
             'Test Village', 'Sonari', '000000000', 'TEST0000001',
             'test-only', 'PENDING', NOW() - INTERVAL '2 days'),
            ('TEST-WD-002', 'Withdrawal Test', %s, '1950-01-01',
             'Test Village', 'Sonari', '000000000', 'TEST0000001',
             'test-only', 'PENDING', NOW() - INTERVAL '1 day')
        RETURNING id, application_no
        """,
        (TEST_MOBILE, TEST_MOBILE),
    )
    test_apps = cur.fetchall()
    print("Created temporary test applications:", test_apps)

    # Run the same single-row withdrawal query used by the MCP tool.
    cur.execute(
        """
        WITH target AS (
            SELECT id
            FROM applications
            WHERE mobile = %s
              AND status = 'PENDING'
            ORDER BY submitted_at DESC, id DESC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE applications AS a
        SET status = 'WITHDRAWN',
            decided_at = NOW(),
            decided_by = 'APPLICANT'
        FROM target
        WHERE a.id = target.id
          AND a.mobile = %s
          AND a.status = 'PENDING'
        RETURNING a.id, a.application_no
        """,
        (TEST_MOBILE, TEST_MOBILE),
    )
    withdrawn = cur.fetchall()
    print("Rows withdrawn:", withdrawn)

    # Audit the row actually withdrawn, just as the MCP tool does.
    for app_id, application_no in withdrawn:
        portal.write_audit(
            cur, app_id, "WITHDRAW", "applicant:" + TEST_MOBILE
        )

    # Verify the two application statuses.
    cur.execute(
        """
        SELECT application_no, status
        FROM applications
        WHERE application_no IN ('TEST-WD-001', 'TEST-WD-002')
        ORDER BY application_no
        """
    )
    statuses = cur.fetchall()
    print("Statuses after withdrawal:", statuses)

    # Verify the audit count.
    cur.execute(
        """
        SELECT COUNT(*)
        FROM audit_log
        WHERE application_id = ANY(%s)
          AND action = 'WITHDRAW'
        """,
        ([app_id for app_id, _ in test_apps],),
    )
    audit_count = cur.fetchone()[0]
    print("Withdrawal audit entries:", audit_count)

    # Assert expected results.
    assert len(withdrawn) == 1, "Expected exactly one row to be withdrawn"
    assert len(statuses) == 2, "Expected two test applications"
    assert sum(status == "WITHDRAWN" for _, status in statuses) == 1
    assert sum(status == "PENDING" for _, status in statuses) == 1
    assert audit_count == 1, "Expected exactly one withdrawal audit entry"

    print("PASS: exactly one application withdrawn and audited.")

finally:
    # Undo the temporary applications and audit entry.
    conn.rollback()
    cur.close()
    conn.close()
    print("Test transaction rolled back; temporary data was not saved.")

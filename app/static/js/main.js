

$(document).ready(function() {
    initializeTooltips();
    initializeEventHandlers();
    initializeCursorBackground();
});


function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

// eevent handlers
function initializeEventHandlers() {
    // auto dismiss alerts after 5 seconds
    $('[role="alert"]').each(function() {
        setTimeout(() => {
            $(this).fadeOut('slow', function() {
                $(this).remove();
            });
        }, 5000);
    });

    // Confirm delete actions
    $('[data-action="delete"]').on('click', function(e) {
        if (!confirm('Are you sure you want to delete this item? This action cannot be undone.')) {
            e.preventDefault();
        }
    });

    // smooth scroll to top
    $(window).scroll(function() {
        if ($(this).scrollTop() > 300) {
            $('#scrollToTop').fadeIn();
        } else {
            $('#scrollToTop').fadeOut();
        }
    });

    $('#scrollToTop').on('click', function() {
        $('html, body').animate({scrollTop: 0}, 600);
    });
}


// issue Book
function issueBook() {
    const studentId = $('#student_id').val();
    const bookId = $('#book_id').val();
    const days = $('#days').val() || 10;

    if (!studentId || !bookId) {
        showAlert('Please select both student and book', 'danger');
        return;
    }

    $.ajax({
        url: '{{ url_for("api_issue_book") }}',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            student_id: studentId,
            book_id: bookId,
            days: days
        }),
        success: function(response) {
            showAlert(response.message, 'success');
            resetIssueForm();
            setTimeout(() => location.reload(), 1500);
        },
        error: function(xhr) {
            const error = xhr.responseJSON?.error || 'An error occurred';
            showAlert(error, 'danger');
        }
    });
}


// return book

function returnBook(issuedId) {
    if (!confirm('Are you sure you want to return this book?')) {
        return;
    }

    $.ajax({
        url: '{{ url_for("api_return_book") }}',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            issued_id: issuedId
        }),
        success: function(response) {
            showAlert(response.message, 'success');
            setTimeout(() => location.reload(), 1500);
        },
        error: function(xhr) {
            const error = xhr.responseJSON?.error || 'An error occurred';
            showAlert(error, 'danger');
        }
    });
}


// add to wishlist

function addToWishlist(studentId, bookId) {
    $.ajax({
        url: '{{ url_for("api_add_wishlist") }}',
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
            student_id: studentId,
            book_id: bookId
        }),
        success: function(response) {
            showAlert('Added to wishlist!', 'success');
        },
        error: function(xhr) {
            const error = xhr.responseJSON?.error || 'Error adding to wishlist';
            showAlert(error, 'danger');
        }
    });
}


// helper functions

function showAlert(message, type = 'info') {
    const alertHtml = `
        <div class="alert alert-${type} alert-dismissible fade show" role="alert">
            <i class="fas fa-${
                type === 'success' ? 'check-circle' :
                type === 'danger' ? 'exclamation-circle' :
                type === 'warning' ? 'exclamation-triangle' :
                'info-circle'
            }"></i>
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
    `;
    
    $('body').prepend(alertHtml);
    
    setTimeout(() => {
        $('.alert').fadeOut('slow', function() {
            $(this).remove();
        });
    }, 5000);
}

function resetIssueForm() {
    $('#issue-form').reset();
    $('#student_id').val('').trigger('change');
    $('#book_id').val('').trigger('change');
    $('#days').val(10);
}

function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-PK', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit'
    });
}

function calculateFine(daysOverdue) {
    return daysOverdue * 5; // 5 PKR per day
}


// search & filter

let searchTimeout;
function liveSearch(searchTerm) {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => {
        if (searchTerm.length > 0) {
            // auto submit form or trigger filtering
            $('[data-search-form]').submit();
        }
    }, 500);
}


// table actions
function deleteItem(itemId, itemType, redirectUrl) {
    if (!confirm(`Are you sure you want to delete this ${itemType}?`)) {
        return;
    }
    
    const form = $(`<form action="${redirectUrl}" method="POST" style="display:none;"></form>`);
    $('body').append(form);
    form.submit();
}


// export functions

function exportTableToCSV(filename = 'export.csv') {
    const table = $('table')[0];
    const csv = [];
    
    //get headers
    const headers = [];
    $('table thead th').each(function() {
        headers.push($(this).text().trim());
    });
    csv.push(headers.join(','));
    
    // get rows
    $('table tbody tr').each(function() {
        const row = [];
        $(this).find('td').each(function() {
            row.push($(this).text().trim());
        });
        csv.push(row.join(','));
    });
    
    // download
    const csvContent = 'data:text/csv;charset=utf-8,' + csv.join('\n');
    const link = document.createElement('a');
    link.setAttribute('href', encodeURI(csvContent));
    link.setAttribute('download', filename);
    link.click();
}

function printTable() {
    const printWindow = window.open('', '', 'height=400,width=800');
    printWindow.document.write('<html><head><title>Print</title>');
    printWindow.document.write('<link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.0/css/bootstrap.min.css" rel="stylesheet">');
    printWindow.document.write('</head><body>');
    printWindow.document.write($('table').html());
    printWindow.document.write('</body></html>');
    printWindow.document.close();
    printWindow.print();
}


// form validation

function validateForm(formId) {
    const form = document.getElementById(formId);
    if (!form.checkValidity() === false) {
        return true;
    }
    
    event.preventDefault();
    event.stopPropagation();
    form.classList.add('was-validated');
    return false;
}

// Cursor-follow background soft glow
function initializeCursorBackground() {
    const overlay = document.getElementById('bg-overlay');
    if (!overlay) return;

    let mouseX = window.innerWidth / 2;
    let mouseY = window.innerHeight / 2;
    let posX = mouseX, posY = mouseY;

    function onMove(e) {
        mouseX = e.clientX || (e.touches && e.touches[0].clientX) || mouseX;
        mouseY = e.clientY || (e.touches && e.touches[0].clientY) || mouseY;
    }

    window.addEventListener('mousemove', onMove, { passive: true });
    window.addEventListener('touchmove', onMove, { passive: true });

    function animate() {
        // ease toward mouse
        posX += (mouseX - posX) * 0.12;
        posY += (mouseY - posY) * 0.12;
        const px = (posX / window.innerWidth) * 100;
        const py = (posY / window.innerHeight) * 100;
        overlay.style.setProperty('--mouse-x', px + '%');
        overlay.style.setProperty('--mouse-y', py + '%');
        requestAnimationFrame(animate);
    }
    requestAnimationFrame(animate);
}


// number formatting

function formatCurrency(amount) {
    return new Intl.NumberFormat('en-PK', {
        style: 'currency',
        currency: 'PKR'
    }).format(amount);
}

function formatNumber(number) {
    return number.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

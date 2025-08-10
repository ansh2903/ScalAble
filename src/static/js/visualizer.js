
        let currentChart = null;
        let currentData = [];
        let currentColumns = [];

        // Color palettes
        const colorPalettes = {
            primary: ['#4facfe', '#00f2fe', '#43e97b', '#38f9d7', '#667eea', '#764ba2'],
            warm: ['#ff9a9e', '#fecfef', '#ffecd2', '#fcb69f', '#ff8a80', '#ffab91'],
            cool: ['#a8edea', '#fed6e3', '#d299c2', '#fef9d7', '#b2fefa', '#0ed2f7'],
            gradient: ['#667eea', '#764ba2', '#f093fb', '#f5576c', '#4facfe', '#00f2fe']
        };

        function parseCSV(csvText) {
            const lines = csvText.trim().split('\n');
            const headers = lines[0].split(',').map(h => h.trim());
            const data = [];

            for (let i = 1; i < lines.length; i++) {
                const values = lines[i].split(',').map(v => v.trim());
                const row = {};
                headers.forEach((header, index) => {
                    row[header] = values[index];
                });
                data.push(row);
            }

            return { headers, data };
        }

        function populateColumnSelects(headers) {
            const selects = ['xAxisSelect', 'yAxisSelect', 'groupBySelect'];
            
            selects.forEach(selectId => {
                const select = document.getElementById(selectId);
                select.innerHTML = selectId === 'groupBySelect' ? '<option value="">No grouping</option>' : '<option value="">Select column...</option>';
                
                headers.forEach(header => {
                    const option = document.createElement('option');
                    option.value = header;
                    option.textContent = header;
                    select.appendChild(option);
                });
            });
        }

        function generateDataStats(data) {
            const stats = {
                totalRows: data.length,
                totalColumns: Object.keys(data[0] || {}).length,
                numericColumns: 0,
                textColumns: 0
            };

            if (data.length > 0) {
                Object.keys(data[0]).forEach(key => {
                    const values = data.map(row => row[key]);
                    const numericValues = values.filter(v => !isNaN(v) && v !== '').length;
                    if (numericValues > values.length * 0.5) {
                        stats.numericColumns++;
                    } else {
                        stats.textColumns++;
                    }
                });
            }

            const statsContainer = document.getElementById('dataStats');
            statsContainer.innerHTML = `
                <div class="stat-card">
                    <div class="stat-value">${stats.totalRows}</div>
                    <div class="stat-label">Total Rows</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.totalColumns}</div>
                    <div class="stat-label">Total Columns</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.numericColumns}</div>
                    <div class="stat-label">Numeric Columns</div>
                </div>
                <div class="stat-card">
                    <div class="stat-value">${stats.textColumns}</div>
                    <div class="stat-label">Text Columns</div>
                </div>
            `;
            statsContainer.style.display = 'grid';
        }

        function generateDataTable(data, headers) {
            const tableContainer = document.getElementById('dataTable');
            let tableHTML = '<table class="table table-hover"><thead><tr>';
            
            headers.forEach(header => {
                tableHTML += `<th>${header}</th>`;
            });
            
            tableHTML += '</tr></thead><tbody>';
            
            data.slice(0, 100).forEach(row => { // Limit to first 100 rows
                tableHTML += '<tr>';
                headers.forEach(header => {
                    tableHTML += `<td>${row[header] || ''}</td>`;
                });
                tableHTML += '</tr>';
            });
            
            tableHTML += '</tbody></table>';
            
            if (data.length > 100) {
                tableHTML += `<p class="text-center mt-2"><small>Showing first 100 rows of ${data.length} total rows</small></p>`;
            }
            
            tableContainer.innerHTML = tableHTML;
            tableContainer.style.display = 'block';
        }

        function createChart(type, xAxis, yAxis, groupBy = '') {
            const ctx = document.getElementById('dataChart').getContext('2d');
            
            if (currentChart) {
                currentChart.destroy();
            }

            if (!xAxis || !yAxis) {
                ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
                const centerX = ctx.canvas.width / 2;
                const centerY = ctx.canvas.height / 2;
                ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
                ctx.font = '18px Segoe UI';
                ctx.textAlign = 'center';
                ctx.fillText('Please select X and Y axis columns', centerX, centerY);
                return;
            }

            let chartData, chartOptions;

            try {
                if (type === 'pie' || type === 'doughnut') {
                    chartData = preparePieData(xAxis, yAxis, groupBy);
                } else if (type === 'scatter') {
                    chartData = prepareScatterData(xAxis, yAxis, groupBy);
                } else {
                    chartData = prepareBarLineData(xAxis, yAxis, groupBy);
                }

                chartOptions = getChartOptions(type, xAxis, yAxis);

                currentChart = new Chart(ctx, {
                    type: type,
                    data: chartData,
                    options: chartOptions
                });
            } catch (error) {
                console.error('Error creating chart:', error);
                ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
                const centerX = ctx.canvas.width / 2;
                const centerY = ctx.canvas.height / 2;
                ctx.fillStyle = 'rgba(255, 100, 100, 0.8)';
                ctx.font = '16px Segoe UI';
                ctx.textAlign = 'center';
                ctx.fillText('Error creating chart. Please check your data and column selections.', centerX, centerY);
            }
        }

        function preparePieData(xAxis, yAxis, groupBy) {
            const aggregatedData = {};
            
            currentData.forEach(row => {
                const key = row[xAxis];
                const value = parseFloat(row[yAxis]) || 0;
                
                if (aggregatedData[key]) {
                    aggregatedData[key] += value;
                } else {
                    aggregatedData[key] = value;
                }
            });

            return {
                labels: Object.keys(aggregatedData),
                datasets: [{
                    data: Object.values(aggregatedData),
                    backgroundColor: colorPalettes.gradient.slice(0, Object.keys(aggregatedData).length),
                    borderColor: 'rgba(255, 255, 255, 0.8)',
                    borderWidth: 2
                }]
            };
        }

        function prepareScatterData(xAxis, yAxis, groupBy) {
            const datasets = [];
            
            if (groupBy) {
                const groups = {};
                currentData.forEach(row => {
                    const group = row[groupBy];
                    if (!groups[group]) groups[group] = [];
                    groups[group].push({
                        x: parseFloat(row[xAxis]) || 0,
                        y: parseFloat(row[yAxis]) || 0
                    });
                });

                Object.keys(groups).forEach((group, index) => {
                    datasets.push({
                        label: group,
                        data: groups[group],
                        backgroundColor: colorPalettes.primary[index % colorPalettes.primary.length] + '80',
                        borderColor: colorPalettes.primary[index % colorPalettes.primary.length],
                        borderWidth: 2
                    });
                });
            } else {
                datasets.push({
                    label: `${xAxis} vs ${yAxis}`,
                    data: currentData.map(row => ({
                        x: parseFloat(row[xAxis]) || 0,
                        y: parseFloat(row[yAxis]) || 0
                    })),
                    backgroundColor: colorPalettes.primary[0] + '80',
                    borderColor: colorPalettes.primary[0],
                    borderWidth: 2
                });
            }

            return { datasets };
        }

        function prepareBarLineData(xAxis, yAxis, groupBy) {
            const labels = [...new Set(currentData.map(row => row[xAxis]))];
            const datasets = [];

            if (groupBy) {
                const groups = [...new Set(currentData.map(row => row[groupBy]))];
                
                groups.forEach((group, index) => {
                    const data = labels.map(label => {
                        const rows = currentData.filter(row => row[xAxis] === label && row[groupBy] === group);
                        return rows.reduce((sum, row) => sum + (parseFloat(row[yAxis]) || 0), 0);
                    });

                    datasets.push({
                        label: group,
                        data: data,
                        backgroundColor: colorPalettes.gradient[index % colorPalettes.gradient.length] + '80',
                        borderColor: colorPalettes.gradient[index % colorPalettes.gradient.length],
                        borderWidth: 2,
                        tension: 0.4
                    });
                });
            } else {
                const data = labels.map(label => {
                    const rows = currentData.filter(row => row[xAxis] === label);
                    return rows.reduce((sum, row) => sum + (parseFloat(row[yAxis]) || 0), 0);
                });

                datasets.push({
                    label: yAxis,
                    data: data,
                    backgroundColor: colorPalettes.primary[0] + '80',
                    borderColor: colorPalettes.primary[0],
                    borderWidth: 2,
                    tension: 0.4
                });
            }

            return { labels, datasets };
        }

        function getChartOptions(type, xAxis, yAxis) {
            const baseOptions = {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        labels: {
                            color: 'white',
                            font: { size: 12 }
                        }
                    },
                    title: {
                        display: true,
                        text: `${yAxis} by ${xAxis}`,
                        color: 'white',
                        font: { size: 16, weight: 'bold' }
                    }
                }
            };

            if (type !== 'pie' && type !== 'doughnut') {
                baseOptions.scales = {
                    x: {
                        ticks: { color: 'white' },
                        grid: { color: 'rgba(255, 255, 255, 0.1)' },
                        title: {
                            display: true,
                            text: xAxis,
                            color: 'white'
                        }
                    },
                    y: {
                        ticks: { color: 'white' },
                        grid: { color: 'rgba(255, 255, 255, 0.1)' },
                        title: {
                            display: true,
                            text: yAxis,
                            color: 'white'
                        }
                    }
                };
            }

            return baseOptions;
        }

        // Event listeners
        document.getElementById('loadData').addEventListener('click', function() {
            const csvText = document.getElementById('dataInput').value.trim();
            
            if (!csvText) {
                alert('Please enter some data first!');
                return;
            }

            try {
                const { headers, data } = parseCSV(csvText);
                currentData = data;
                currentColumns = headers;

                populateColumnSelects(headers);
                generateDataStats(data);
                generateDataTable(data, headers);

                // Auto-select first numeric columns
                const numericColumns = headers.filter(header => {
                    const values = data.map(row => row[header]);
                    const numericValues = values.filter(v => !isNaN(v) && v !== '').length;
                    return numericValues > values.length * 0.5;
                });

                if (numericColumns.length >= 2) {
                    document.getElementById('yAxisSelect').value = numericColumns[0];
                }
                
                const textColumns = headers.filter(h => !numericColumns.includes(h));
                if (textColumns.length > 0) {
                    document.getElementById('xAxisSelect').value = textColumns[0];
                }

                updateChart();
                
            } catch (error) {
                alert('Error parsing data. Please check your CSV format.');
                console.error(error);
            }
        });

        document.querySelectorAll('.chart-type-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                document.querySelectorAll('.chart-type-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                updateChart();
            });
        });

        function updateChart() {
            const activeChartType = document.querySelector('.chart-type-btn.active').dataset.type;
            const xAxis = document.getElementById('xAxisSelect').value;
            const yAxis = document.getElementById('yAxisSelect').value;
            const groupBy = document.getElementById('groupBySelect').value;
            
            createChart(activeChartType, xAxis, yAxis, groupBy);
        }

        document.getElementById('xAxisSelect').addEventListener('change', updateChart);
        document.getElementById('yAxisSelect').addEventListener('change', updateChart);
        document.getElementById('groupBySelect').addEventListener('change', updateChart);

        // Load sample data on page load
        window.addEventListener('load', function() {
            document.getElementById('loadData').click();
        });